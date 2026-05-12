"""Public REST surface — every shipped CricDex feature is callable here.

Conventions
-----------
- All read endpoints are GET with query-string params.
- Outputs are JSON — either a list of records or a single object.
- Write-shape endpoints (rules QA, translate, auction solve) are POST
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
from cricdex.commentary_translate import translate as ct
from cricdex.comparator import compare as comparator
from cricdex.profiles import builder as profiles
from cricdex.records import queries as records
from cricdex.reports import match_report
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
        raise HTTPException(
            status_code=404, detail=f"{name!r} not found in feature table"
        ) from e


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


# ---- match reports --------------------------------------------------------


@app.get("/v1/match-reports/{match_id}")
def match_report_endpoint(match_id: str, collection: str = Query("ipl")) -> dict[str, str]:
    path = match_report.generate(match_id=match_id, collection=collection)
    return {"match_id": match_id, "collection": collection, "report_md": path.read_text()}


# ---- translate ------------------------------------------------------------


class TranslateReq(BaseModel):
    text: str
    target: str = "hi"


@app.post("/v1/translate")
def translate_endpoint(req: TranslateReq) -> dict[str, str]:
    if req.target not in ct.TARGETS:
        raise HTTPException(status_code=422, detail=f"unsupported target {req.target!r}")
    return {"target": req.target, "translated": ct.translate(req.text, target=req.target)}


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
