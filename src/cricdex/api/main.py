"""Public REST surface — every shipped CricDex feature is callable here.

Conventions
-----------
- All read endpoints are GET with query-string params.
- Outputs are JSON — either a list of records or a single object.
- Write-shape endpoints (rules QA, auction solve) are POST
  with a JSON body for forward-compat.
- No auth yet; expose only behind a reverse proxy with rate-limiting
  in front (Cloudflare Workers planned).
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from cricdex import __version__
from cricdex.auction import solver as auction_solver
from cricdex.comparator import compare as comparator
from cricdex.profiles import builder as profiles
from cricdex.records import queries as records
from cricdex.rules import qa as rules_qa
from cricdex.scout.search import style_twin as st
from cricdex.venues import profile as venues

app = FastAPI(
    title="CricDex API",
    version=__version__,
    description="Open cricket intelligence — REST surface over every module.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


# ---- records ---------------------------------------------------------------


@app.get("/v1/records")
def list_records() -> dict[str, list[str]]:
    return {"records": list(records.RECORDS.keys())}


@app.get("/v1/records/{record}")
def record_top(
    record: str,
    collection: str = Query("ipl"),
    top_n: int = Query(25, ge=1, le=200),
) -> list[dict]:
    if record not in records.RECORDS:
        raise HTTPException(status_code=404, detail=f"unknown record {record!r}")
    return records.RECORDS[record](collection, top_n=top_n).to_dicts()


@app.get("/v1/records-on-this-day")
def records_on_this_day(
    month: int = Query(..., ge=1, le=12),
    day: int = Query(..., ge=1, le=31),
    collection: str = Query("ipl"),
    top_n: int = Query(50, ge=1, le=200),
) -> list[dict]:
    return records.on_this_day(month=month, day=day, collection=collection, top_n=top_n).to_dicts()


# ---- venues ----------------------------------------------------------------


@app.get("/v1/venues")
def venues_list(
    collection: str = Query("ipl"),
    min_matches: int = Query(5, ge=1, le=200),
) -> list[dict]:
    return venues.list_venues(collection, min_matches=min_matches).to_dicts()


@app.get("/v1/venues/{venue}/profile")
def venue_profile(venue: str, collection: str = Query("ipl")) -> dict[str, Any]:
    return {
        "venue": venue,
        "innings_totals": venues.innings_totals(venue, collection).to_dicts(),
        "chase_vs_set": venues.chase_vs_set_winrate(venue, collection).to_dicts(),
        "phase_run_rates": venues.phase_run_rates(venue, collection).to_dicts(),
        "dismissal_mix": venues.dismissal_mix(venue, collection).to_dicts(),
    }


# ---- players ---------------------------------------------------------------


@app.get("/v1/players/{name}")
def player_profile(name: str, collection: str = Query("ipl")) -> dict[str, Any]:
    return profiles.build(name, collection=collection)


@app.get("/v1/players/{name}/style-twins")
def player_style_twins(
    name: str,
    role: str = Query("batter", pattern="^(batter|bowler)$"),
    k: int = Query(10, ge=1, le=50),
    collection: str = Query("ipl"),
) -> list[dict]:
    try:
        return st.style_twin(name, role=role, k=k, collection=collection).to_dicts()
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"{name!r} not found in feature table") from e


class CompareReq(BaseModel):
    players: list[str]
    collection: str = "ipl"


@app.post("/v1/compare")
def compare_players(req: CompareReq) -> list[dict]:
    if len(req.players) < 2:
        raise HTTPException(status_code=422, detail="need ≥2 players to compare")
    return comparator.compare(req.players, collection=req.collection).to_dicts()


# ---- rules ----------------------------------------------------------------


class RulesAskReq(BaseModel):
    query: str
    formats: list[str] | None = None
    top_k: int = 8


@app.post("/v1/rules/ask")
def rules_ask(req: RulesAskReq) -> dict[str, Any]:
    res = rules_qa.answer(req.query, formats=req.formats, top_k=req.top_k)
    return {
        "answer": res["answer"],
        "citations": [{"source_id": s, "law_number": l_} for s, l_ in res["citations"]],
        "llm_used": res.get("llm_used"),
    }


# ---- auction --------------------------------------------------------------


class AuctionPoolRow(BaseModel):
    name: str
    role: str
    country: str | None = None
    is_overseas: bool = False
    price: float
    projected_value: float


class AuctionSolveReq(BaseModel):
    pool: list[AuctionPoolRow]
    purse: float = 120.0
    squad_size: int = 25
    overseas_cap: int = 8
    role_mins: dict[str, int] | None = None


@app.post("/v1/auction/solve")
def auction_solve(req: AuctionSolveReq) -> dict[str, Any]:
    import polars as pl

    if not req.pool:
        raise HTTPException(status_code=422, detail="empty pool")
    pool_df = pl.DataFrame([row.model_dump() for row in req.pool])
    result = auction_solver.solve(
        pool_df,
        purse=req.purse,
        squad_size=req.squad_size,
        overseas_cap=req.overseas_cap,
        role_mins=req.role_mins,
    )
    return {
        "feasible": result["feasible"],
        "total_price": result.get("total_price"),
        "total_value": result.get("total_value"),
        "selected": result["selected"].to_dicts() if not result["selected"].is_empty() else [],
        "reason": result.get("reason"),
    }


# ---- metrics ---------------------------------------------------------------


@app.get("/v1/metrics/ngi")
def metrics_ngi(
    collection: str = Query("ipl"),
    min_matches: int = Query(20, ge=0),
    top_n: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    """NGI (Net Game Impact) leaderboard. Reads the pre-computed JSON
    written by `scripts/compute_metrics.py ngi` if present; otherwise
    falls back to a live fit on the requested collection."""
    import json

    import polars as pl

    from cricdex.config import DATA_DIR

    cached = DATA_DIR / "metrics" / f"ngi_{collection}.json"
    if cached.exists():
        rows = json.loads(cached.read_text())
        df = pl.DataFrame(rows)
    else:
        from cricdex.metrics import ngi as _ngi

        res = _ngi.compute(collection=collection)
        df = res["career"]
        if df.is_empty():
            raise HTTPException(404, f"no NGI data for collection {collection!r}")
    if "matches" in df.columns:
        df = df.filter(pl.col("matches") >= min_matches)
    if "ngi_per_match" in df.columns:
        df = df.sort("ngi_per_match", descending=True)
    return {"collection": collection, "rows": df.head(top_n).to_dicts()}


# ---- auction advisor -------------------------------------------------------


class AuctionRecommendReq(BaseModel):
    target: str
    budget: float
    role: str | None = None
    n: int = 5
    min_last_match_date: str | None = "2023-01-01"
    max_balls_bowled: int | None = None
    max_balls_faced: int | None = None
    collection: str = "ipl"


@app.post("/v1/auction/recommend")
def auction_recommend(req: AuctionRecommendReq) -> dict[str, Any]:
    """Find affordable graph-similar substitutes for an unavailable
    target player. Composite of FACED-cohort similarity + Bayes-driven
    projected value, filtered to budget + role."""
    try:
        from cricdex.auction import advisor
    except ImportError as e:
        raise HTTPException(503, f"auction.advisor unavailable: {e}") from e
    rec = advisor.recommend_substitutes(
        req.target,
        budget=req.budget,
        role=req.role,
        n=req.n,
        min_last_match_date=req.min_last_match_date,
        max_balls_bowled=req.max_balls_bowled,
        max_balls_faced=req.max_balls_faced,
        collection=req.collection,
    )
    if rec.is_empty():
        return {"target": req.target, "budget": req.budget, "rows": []}
    return {"target": req.target, "budget": req.budget, "rows": rec.to_dicts()}


# ---- scout graph twins -----------------------------------------------------


@app.get("/v1/scout/twins/{name}")
def scout_twins(
    name: str,
    mode: str = Query("co_faced", pattern="^(co_faced|teammates)$"),
    top_k: int = Query(10, ge=1, le=50),
    collection: str = Query("ipl"),
) -> dict[str, Any]:
    """Graph-traversal similarity. `mode=co_faced` returns players
    sharing FACED bowlers (batter affinity); `mode=teammates` returns
    teammate-overlap cohort."""
    try:
        from cricdex.scout.graph import similar
    except ImportError as e:
        raise HTTPException(503, f"scout.graph unavailable (neo4j extra?): {e}") from e
    if mode == "co_faced":
        rows = similar.co_faced_bowlers(name, top_k=top_k, collection=collection)
    else:
        rows = similar.teammate_overlap(name, top_k=top_k, collection=collection)
    return {"target": name, "mode": mode, "rows": rows}


@app.get("/v1/scout/find-replacement/{name}")
def scout_find_replacement(
    name: str,
    top_k: int = Query(10, ge=1, le=50),
    role: str | None = Query(None, pattern="^(bowler|batter|all_rounder)$"),
    max_balls_bowled: int | None = Query(None, ge=0),
    max_balls_faced: int | None = Query(None, ge=0),
    min_last_match_date: str | None = Query(None),
    collection: str = Query("ipl"),
) -> dict[str, Any]:
    """Find replacement / "next X" — auto-flips the FACED traversal
    direction based on the target's role, applies recency + role +
    balls filters."""
    try:
        from cricdex.scout.graph import similar
    except ImportError as e:
        raise HTTPException(503, f"scout.graph unavailable (neo4j extra?): {e}") from e
    rows = similar.find_replacement(
        name,
        top_k=top_k,
        role=role,
        max_balls_bowled=max_balls_bowled,
        max_balls_faced=max_balls_faced,
        min_last_match_date=min_last_match_date,
        collection=collection,
    )
    return {"target": name, "role": role, "rows": rows}
