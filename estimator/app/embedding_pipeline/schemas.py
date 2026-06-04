"""Pydantic v2 schemas for the embedding pipeline (Session 7).

These models describe three things:

1. The **input** documents (`Budget`, `BudgetComponent`, `ClientMetadata`) —
   the normalised historical budgets produced in Session 6.
2. The **intermediate** unit of work (`Chunk`) and its vectorised form
   (`EmbeddedChunk`) — what the chunker emits and the embedder enriches.
3. The **HTTP contract** (`IngestRequest`, `IngestResponse`, `IngestStats`) of
   ``POST /embeddings/ingest``.

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
# HTTP contract
# --------------------------------------------------------------------------- #
class IngestRequest(BaseModel):
    """Body of ``POST /embeddings/ingest``."""

    model_config = ConfigDict(extra="forbid")

    budgets: list[Budget] = Field(min_length=1)


class IngestStats(BaseModel):
    """Aggregated statistics returned alongside the vectorised chunks."""

    total_budgets: int
    total_chunks: int
    total_tokens: int
    estimated_cost_usd: float


class IngestResponse(BaseModel):
    """Response of ``POST /embeddings/ingest`` (HTTP 200)."""

    chunks: list[EmbeddedChunk]
    stats: IngestStats
