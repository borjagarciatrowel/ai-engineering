"""FastAPI router for the embedding pipeline (Session 7).

Exposes ``POST /embeddings/ingest``. The handler is a thin orchestrator:

    chunker.chunk(budgets) -> embedder.embed_many(chunks) -> IngestResponse

Status codes:
* 200 — success.
* 422 — Pydantic validation failure (handled automatically by FastAPI).
* 500 — uncontrolled error from the embeddings API. The client gets a generic
  message; the detail is logged.
* 503 — embeddings are not configured (no OpenAI API key).
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_openai_embedder
from app.embedding_pipeline.chunker import JSONStructuralChunker
from app.embedding_pipeline.embedder import OpenAIEmbedder, estimated_cost_usd
from app.embedding_pipeline.schemas import IngestRequest, IngestResponse, IngestStats

log = structlog.get_logger()

router = APIRouter(prefix="/embeddings", tags=["embeddings"])

_chunker = JSONStructuralChunker()


@router.post("/ingest", response_model=IngestResponse)
def ingest_embeddings(
    request: IngestRequest,
    embedder: OpenAIEmbedder = Depends(get_openai_embedder),
) -> IngestResponse:
    chunks = _chunker.chunk(request.budgets)

    try:
        embedded_chunks = embedder.embed_many(chunks)
    except Exception as exc:  # noqa: BLE001
        # Generic message to the client, full detail in the logs.
        log.error(
            "embeddings_ingest_failed",
            error_type=type(exc).__name__,
            error=str(exc)[:400],
            total_chunks=len(chunks),
        )
        raise HTTPException(
            status_code=500, detail="embedding generation failed"
        ) from exc

    total_tokens = sum(c.token_count for c in chunks)
    stats = IngestStats(
        total_budgets=len(request.budgets),
        total_chunks=len(chunks),
        total_tokens=total_tokens,
        estimated_cost_usd=round(estimated_cost_usd(total_tokens), 6),
    )
    log.info(
        "embeddings_ingest_completed",
        total_budgets=stats.total_budgets,
        total_chunks=stats.total_chunks,
        total_tokens=stats.total_tokens,
        estimated_cost_usd=stats.estimated_cost_usd,
    )
    return IngestResponse(chunks=embedded_chunks, stats=stats)
