"""Minimal embeddings + chunking pipeline (Session 7).

Receives historical budgets (JSON), splits them into chunks respecting the
document structure (one component = one chunk), generates embeddings with OpenAI
``text-embedding-3-small`` and returns the vectors over HTTP. No vector-store
persistence yet — that arrives in Session 8 (PostgreSQL + pgvector).
"""
from __future__ import annotations

from app.embedding_pipeline.chunker import JSONStructuralChunker
from app.embedding_pipeline.embedder import OpenAIEmbedder, estimated_cost_usd
from app.embedding_pipeline.schemas import (
    Budget,
    BudgetComponent,
    Chunk,
    ClientMetadata,
    EmbeddedChunk,
    IngestRequest,
    IngestResponse,
    IngestStats,
)

__all__ = [
    "JSONStructuralChunker",
    "OpenAIEmbedder",
    "estimated_cost_usd",
    "Budget",
    "BudgetComponent",
    "Chunk",
    "ClientMetadata",
    "EmbeddedChunk",
    "IngestRequest",
    "IngestResponse",
    "IngestStats",
]
