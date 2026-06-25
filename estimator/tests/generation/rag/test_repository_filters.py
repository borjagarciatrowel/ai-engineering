"""Pure unit tests for ``ChunkStore._structural_filters`` (no DB).

The staticmethod builds the SQLAlchemy predicate list shared by ``search_filtered``
and ``search_lexical``; each non-``None`` axis (sector / year-min / year-max /
chunk_type) contributes exactly one predicate, ``None`` axes contribute none.
We assert on the predicate COUNT, which needs no engine or session.
"""

from __future__ import annotations

from app.generation.rag.store.repository import ChunkStore


def test_structural_filters_counts_predicates():
    filters = ChunkStore._structural_filters(
        sectors=["finance"],
        project_year_min=2020,
        project_year_max=None,
        chunk_types=None,
    )
    assert len(filters) == 2


def test_structural_filters_empty():
    filters = ChunkStore._structural_filters(
        sectors=None,
        project_year_min=None,
        project_year_max=None,
        chunk_types=None,
    )
    assert len(filters) == 0


def test_structural_filters_all_axes():
    filters = ChunkStore._structural_filters(
        sectors=["finance", "ecommerce"],
        project_year_min=2020,
        project_year_max=2024,
        chunk_types=["budget_component"],
    )
    assert len(filters) == 4
