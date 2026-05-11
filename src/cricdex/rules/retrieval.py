"""Hybrid retrieval (dense + BM25 fused via RRF) over rule clauses.

Lazy global caches for embedding model + Qdrant client + BM25 index so the
CLI / API can answer many queries without reloading.
"""

from __future__ import annotations

from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchAny
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

from cricdex.config import DATA_DIR
from cricdex.rules.embed import COLLECTION, EMBED_MODEL, load_clauses

_model: SentenceTransformer | None = None
_client: QdrantClient | None = None
_bm25: BM25Okapi | None = None
_clauses: list[dict] | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBED_MODEL)
    return _model


def _get_client(path: Path | None = None) -> QdrantClient:
    global _client
    if _client is None:
        path = path or (DATA_DIR / "rules" / "qdrant")
        _client = QdrantClient(path=str(path))
    return _client


def _get_bm25(parsed_dir: Path | None = None) -> tuple[BM25Okapi, list[dict]]:
    global _bm25, _clauses
    if _bm25 is None or _clauses is None:
        parsed_dir = parsed_dir or (DATA_DIR / "rules" / "parsed")
        _clauses = load_clauses(parsed_dir)
        tokens = [(c["title"] + " " + c["text"]).lower().split() for c in _clauses]
        _bm25 = BM25Okapi(tokens)
    return _bm25, _clauses


def _source_filter(source_ids: list[str] | None) -> Filter | None:
    if not source_ids:
        return None
    return Filter(must=[FieldCondition(key="source_id", match=MatchAny(any=source_ids))])


def dense_search(
    query: str,
    top_k: int = 20,
    source_ids: list[str] | None = None,
) -> list[tuple[float, dict]]:
    model = _get_model()
    client = _get_client()
    vec = model.encode([query], normalize_embeddings=True)[0].tolist()
    hits = client.query_points(
        collection_name=COLLECTION,
        query=vec,
        limit=top_k,
        query_filter=_source_filter(source_ids),
    ).points
    return [(h.score, h.payload) for h in hits]


def sparse_search(
    query: str,
    top_k: int = 20,
    source_ids: list[str] | None = None,
) -> list[tuple[float, dict]]:
    bm25, clauses = _get_bm25()
    scores = bm25.get_scores(query.lower().split())
    indexed = list(enumerate(scores))
    if source_ids:
        wanted = set(source_ids)
        indexed = [(i, s) for i, s in indexed if clauses[i]["source_id"] in wanted]
    indexed.sort(key=lambda x: x[1], reverse=True)
    return [(float(s), clauses[i]) for i, s in indexed[:top_k]]


def _payload_key(p: dict) -> tuple:
    return (p["source_id"], p["law_number"], p.get("page"))


def rrf_fuse(
    dense_hits: list[tuple[float, dict]],
    sparse_hits: list[tuple[float, dict]],
    top_k: int = 10,
    k_const: int = 60,
) -> list[tuple[float, dict]]:
    scores: dict[tuple, float] = {}
    payloads: dict[tuple, dict] = {}
    for rank, (_, p) in enumerate(dense_hits):
        k = _payload_key(p)
        scores[k] = scores.get(k, 0.0) + 1.0 / (k_const + rank + 1)
        payloads[k] = p
    for rank, (_, p) in enumerate(sparse_hits):
        k = _payload_key(p)
        scores[k] = scores.get(k, 0.0) + 1.0 / (k_const + rank + 1)
        payloads[k] = p
    fused = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    return [(s, payloads[k]) for k, s in fused]


def hybrid_search(
    query: str,
    top_k: int = 10,
    source_ids: list[str] | None = None,
) -> list[tuple[float, dict]]:
    dense = dense_search(query, top_k=top_k * 2, source_ids=source_ids)
    sparse = sparse_search(query, top_k=top_k * 2, source_ids=source_ids)
    return rrf_fuse(dense, sparse, top_k=top_k)
