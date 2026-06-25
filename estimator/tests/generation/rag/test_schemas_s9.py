"""Validation tests for the Session 9 RAG estimation/retrieval schemas."""

from __future__ import annotations

from app.generation.rag.schemas import (
    BudgetComponent,
    Estimate,
    RetrievalResult,
    RetrievedChunk,
)


def test_estimate_insufficient_validates() -> None:
    estimate = Estimate(confidence="insufficient", reasoning="x")
    assert estimate.total_engineer_days is None
    assert estimate.modules == []


def test_retrieved_chunk_validates() -> None:
    chunk = RetrievedChunk(
        id=1,
        content="c",
        sector="finance",
        project_year=2024,
        chunk_type="budget_component",
        distance=0.1,
    )
    assert chunk.budget_id is None


def test_retrieval_result_validates() -> None:
    result = RetrievalResult(chunks=[], low_confidence=True, candidates_evaluated=0)
    assert result.low_confidence is True
    assert result.candidates_evaluated == 0


def test_budget_component_module_optional() -> None:
    component = BudgetComponent(
        component_id="AUTH-001",
        name="Login",
        description="Email + password login.",
        estimated_hours=10,
        complexity="low",
    )
    assert component.module is None
