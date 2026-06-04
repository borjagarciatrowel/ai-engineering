"""Structural chunker for budget JSON (Session 7).

Strategy: **one budget component == one chunk**. We trust the structure of the
document instead of doing fixed-size or overlap splitting. A component is a
self-contained unit of meaning that comfortably fits a single chunk.

Each chunk's ``text`` is a *contextual chunk header* (the parent budget's
project/sector/year/tech) followed by the component detail. Without the parent
context, a chunk like "Authentication backend" would lose the trace of which
client and sector it belongs to — and embeddings of bare component descriptions
would collapse together across very different projects.
"""
from __future__ import annotations

import functools

import tiktoken

from app.embedding_pipeline.schemas import Budget, BudgetComponent, Chunk

# The embedding model whose tokenizer we use to count tokens. Counting with the
# *same* model that will embed the text lets us catch abnormally large chunks
# before paying for an API call.
EMBEDDING_MODEL = "text-embedding-3-small"


@functools.lru_cache(maxsize=1)
def _encoding() -> tiktoken.Encoding:
    """Cached tiktoken encoding for the embedding model."""
    return tiktoken.encoding_for_model(EMBEDDING_MODEL)


def _render_text(budget: Budget, component: BudgetComponent) -> str:
    """Render the embeddable text: parent context header + component detail."""
    tech_stack = ", ".join(component.tech_stack)
    return (
        f"[Project: {budget.project_summary}]\n"
        f"[Client sector: {budget.client_metadata.sector} | "
        f"Year: {budget.year} | Main tech: {budget.main_technology}]\n"
        f"\n"
        f"Component: {component.name}\n"
        f"Description: {component.description}\n"
        f"Tech stack: {tech_stack}\n"
        f"Complexity: {component.complexity}\n"
        f"Estimated hours: {component.estimated_hours}"
    )


class JSONStructuralChunker:
    """Turns a list of budgets into a flat list of chunks (one per component)."""

    def chunk(self, budgets: list[Budget]) -> list[Chunk]:
        chunks: list[Chunk] = []
        encoding = _encoding()
        for budget in budgets:
            for component in budget.components:
                text = _render_text(budget, component)
                chunks.append(
                    Chunk(
                        chunk_id=f"{budget.budget_id}::{component.component_id}",
                        text=text,
                        token_count=len(encoding.encode(text)),
                        metadata={
                            # Filterable fields that travel with the chunk but
                            # are NOT part of the embedded text.
                            "budget_id": budget.budget_id,
                            "component_id": component.component_id,
                            "client_sector": budget.client_metadata.sector,
                            "main_technology": budget.main_technology,
                            "year": budget.year,
                            "complexity": component.complexity,
                            "estimated_hours": component.estimated_hours,
                        },
                    )
                )
        return chunks
