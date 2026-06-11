"""Pydantic v2 schemas for the embedding pipeline (Sessions 7 + 8).

These models describe three things:

1. The **input** documents (`Budget`, `BudgetComponent`, `ClientMetadata`) —
   the normalised historical budgets produced in Session 6.
2. The **intermediate** unit of work (`Chunk`) and its vectorised form
   (`EmbeddedChunk`) — what the chunker emits and the embedder enriches.
3. The **HTTP contract** of the persisting pipeline (Session 8):
   ``POST /embeddings/ingest`` (`IngestRequest` / `IngestResponse`) and
   ``POST /search`` (`SearchRequest` / `SearchResponse` / `SearchHit`).

Session 8 changed the ingest contract: ``/embeddings/ingest`` no longer returns
chunks+vectors over HTTP. It persists one document plus its embedded chunks in
pgvector and returns only identifiers and metrics; the vectors live in the DB.

All names are in English to stay consistent with the rest of the codebase, and
validators are explicit where the universe of values is known (``complexity``).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Closed set: a component's complexity is a well-known three-value scale. Other
# string fields (sector, country, main_technology) are left open on purpose —
# their universe is not fixed and a Literal would reject valid future data.
Complexity = Literal["low", "medium", "high"]


# --------------------------------------------------------------------------- #
# Input documents
# --------------------------------------------------------------------------- #
class ClientMetadata(BaseModel):
    """Client-level context attached to every budget."""

    model_config = ConfigDict(extra="ignore")

    name: str
    sector: str = Field(description="e.g. fintech, e-commerce, healthcare, industrial")
    country: str = Field(description="ISO-ish country code, e.g. ES, DE, US")


class BudgetComponent(BaseModel):
    """A single component (line item) of a budget. One component == one chunk."""

    model_config = ConfigDict(extra="ignore")

    component_id: str
    name: str
    description: str
    tech_stack: list[str] = Field(default_factory=list)
    estimated_hours: int = Field(ge=0)
    complexity: Complexity
    dependencies: list[str] = Field(default_factory=list)


class Budget(BaseModel):
    """A complete historical budget with its components."""

    model_config = ConfigDict(extra="ignore")

    budget_id: str
    client_metadata: ClientMetadata
    project_summary: str
    main_technology: str
    year: int
    total_estimated_hours: int = Field(ge=0)
    components: list[BudgetComponent] = Field(min_length=1)


# --------------------------------------------------------------------------- #
# Chunks
# --------------------------------------------------------------------------- #
class Chunk(BaseModel):
    """A fragment ready to embed.

    ``text`` is the only field that gets sent to the embedding model. ``metadata``
    travels with the chunk for future filtering but is NOT embedded.
    """

    chunk_id: str = Field(description="Traceable id, format {budget_id}::{component_id}")
    text: str
    metadata: dict = Field(default_factory=dict)
    token_count: int = Field(ge=0, description="tiktoken token count of `text`")


class EmbeddedChunk(Chunk):
    """A `Chunk` plus its embedding vector."""

    embedding: list[float]


# --------------------------------------------------------------------------- #
# HTTP contract — Session 8 (persisting ingest + semantic search)
# --------------------------------------------------------------------------- #
class IngestRequest(BaseModel):
    """Payload for ``POST /embeddings/ingest`` (Session 8: persisting contract).

    One request = one document. ``content`` is the full budget JSON, validated
    against :class:`Budget` so a malformed corpus fails with a 422 before
    touching the database or the embeddings API.
    """

    model_config = ConfigDict(extra="forbid")

    source_path: str = Field(
        min_length=1, description="Provenance of the document, unique per ingest."
    )
    document_type: str = Field(
        min_length=1, max_length=50, description="Document family, e.g. 'historical_budget'."
    )
    content: Budget = Field(description="Full budget JSON, as produced upstream.")


class IngestResponse(BaseModel):
    """Response for ``POST /embeddings/ingest``: identifiers + ingest metrics.

    Vectors no longer travel over HTTP — they are persisted in pgvector.
    """

    document_id: int = Field(description="Primary key of the persisted document.")
    chunks_created: int = Field(ge=0, description="Chunks persisted for this document.")
    embedding_dimension: int = Field(description="Dimensionality of the stored vectors.")
    ingestion_time_ms: int = Field(ge=0, description="Wall-clock ingest time.")


class SearchRequest(BaseModel):
    """Payload for ``POST /search``."""

    query: str = Field(min_length=1, description="Free-text semantic query.")
    k: int = Field(default=5, ge=1, le=50, description="Number of nearest chunks to return.")


class SearchHit(BaseModel):
    """One ranked chunk. ``chunk_id`` is the DB primary key; the traceable
    corpus id ('BUD-X::COMP-Y' parts) travels inside ``metadata``."""

    chunk_id: int
    document_id: int
    chunk_type: str
    content: str
    distance: float = Field(description="Cosine distance (lower = more similar).")
    metadata: dict


class SearchResponse(BaseModel):
    """Response for ``POST /search``."""

    query: str
    k: int
    search_time_ms: int = Field(ge=0)
    results: list[SearchHit]
