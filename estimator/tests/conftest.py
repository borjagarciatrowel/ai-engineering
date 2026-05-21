"""Shared fixtures.

The conversational tests (Session 5) run fully offline:
- ``sqlite_db`` swaps Postgres for an in-memory sqlite so the DB-backed
  ``DbSessionStore`` works without a real database. Because ``get_session_store``
  depends on ``get_db``, overriding ``get_db`` is enough — the store transparently
  uses sqlite.
- ``FakeLLMWrapper`` replaces real LLM calls with scripted EstimationResult /
  ProjectMetadata pairs, one pair per turn.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db_models  # noqa: F401 — register ORM models on Base.metadata
from app.db import Base, get_db
from app.dependencies import (
    get_estimation_service,
    get_llm_wrapper,
    get_openai_client,
)
from app.main import app
from app.schemas.estimation import EstimationResult
from app.services.estimation import EstimationService
from app.sessions.models import ProjectMetadata


@pytest.fixture
def client() -> TestClient:
    """Provide a FastAPI test client configured with the application."""
    return TestClient(app)


@pytest.fixture
def sqlite_db():
    """In-memory sqlite shared across connections; overrides ``get_db``.

    Yields the ``sessionmaker`` so a test can open its own session to inspect
    the persisted ``chat_sessions`` row directly.
    """
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)

    def _override():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    try:
        yield TestingSession
    finally:
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(engine)


# ---- Shared fakes for the conversational integration tests ----


def make_canned_result(
    *,
    total_cost_eur: int = 25_000,
    total_duration_weeks: int = 6,
    confidence_pct: int = 72,
) -> EstimationResult:
    return EstimationResult(
        summary="Canned CRM build for the sales team.",
        confidence_pct=confidence_pct,
        phases=[
            {"name": "Discovery", "duration_weeks": 1, "cost_eur": 5_000,
             "summary": "Scoping workshops + tech spike."},
            {"name": "Build", "duration_weeks": total_duration_weeks - 1,
             "cost_eur": total_cost_eur - 5_000,
             "summary": "Core build with React + Postgres."},
        ],
        total_duration_weeks=total_duration_weeks,
        total_cost_eur=total_cost_eur,
    )


class FakeLLMWrapper:
    """In-process double of ``LLMWrapper`` for conversational tests.

    Captures every ``complete_structured_chat`` call. Returns scripted
    EstimationResult / ProjectMetadata pairs in order, one pair per turn.
    """

    primary_model = "gpt-4o-mini"

    def __init__(self) -> None:
        self.chat_calls: list[dict] = []
        self.scripted: list[tuple[EstimationResult, ProjectMetadata]] = []
        self._turn = 0

    def add_turn(
        self,
        *,
        result: EstimationResult | None = None,
        metadata: ProjectMetadata | None = None,
    ) -> None:
        self.scripted.append(
            (result or make_canned_result(), metadata or ProjectMetadata())
        )

    def complete_structured_chat(self, *, messages, response_model, **kwargs):
        self.chat_calls.append(
            {
                "messages": messages,
                "response_model": response_model.__name__,
                "kwargs": kwargs,
            }
        )
        idx = self._turn // 2
        if idx >= len(self.scripted):
            # Pad with neutral results so tests that exercise extra turns
            # (sliding window) don't have to script every single one.
            self.scripted.append((make_canned_result(), ProjectMetadata()))
        result, metadata = self.scripted[idx]
        self._turn += 1
        meta = {
            "model": "gpt-4o-mini",
            "provider": "openai",
            "latency_ms": 1,
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
            "cost_usd": 0.0,
            "finish_reason": "stop",
        }
        if response_model is EstimationResult:
            return result, meta
        return metadata, meta


@pytest.fixture
def fake_wrapper() -> FakeLLMWrapper:
    return FakeLLMWrapper()


@pytest.fixture
def conversational_client(sqlite_db, fake_wrapper: FakeLLMWrapper):
    """Wire FastAPI to use the fake wrapper + the sqlite-backed session store.

    ``get_session_store`` is NOT overridden: it depends on ``get_db``, which
    ``sqlite_db`` already points at the in-memory database. Yields
    ``(client, session_factory)`` so tests can inspect the persisted row.
    """
    service = EstimationService(
        llm_wrapper=fake_wrapper,
        exact_cache=None,
        semantic_cache=None,
        openai_client=None,
        metadata_extractor_model="gpt-4o-mini",
    )
    app.dependency_overrides[get_estimation_service] = lambda: service
    app.dependency_overrides[get_llm_wrapper] = lambda: fake_wrapper
    app.dependency_overrides[get_openai_client] = lambda: None

    with TestClient(app) as c:
        yield c, sqlite_db

    for dep in (get_estimation_service, get_llm_wrapper, get_openai_client):
        app.dependency_overrides.pop(dep, None)
