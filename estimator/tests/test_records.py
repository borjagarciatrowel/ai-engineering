"""CRUD + lifecycle tests for the persisted-estimation API.

The DB is an in-memory sqlite (``get_db`` overridden) and the pipeline is a fake
(``get_estimation_service`` overridden), so these tests never touch Postgres,
Redis or a real LLM.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db_models  # noqa: F401 — register the ORM model on Base.metadata
from app.db import Base, get_db
from app.dependencies import get_estimation_service
from app.guardrails.input import InputGuardrailViolation
from app.main import app
from app.schemas.estimation import EstimationResponse, EstimationResult, LlmUsage

LONG_DESC = "A small B2B SaaS to manage employee equipment loans across teams."


@pytest.fixture
def sqlite_db():
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
    yield
    app.dependency_overrides.pop(get_db, None)
    Base.metadata.drop_all(engine)


def _canned() -> EstimationResult:
    return EstimationResult(
        summary="Mid-sized B2B SaaS for equipment loans.",
        confidence_pct=70,
        phases=[
            {"name": "Discovery", "duration_weeks": 1, "cost_eur": 5_000, "summary": "Scope and spike."},
            {"name": "Build", "duration_weeks": 6, "cost_eur": 20_000, "summary": "Core feature build."},
        ],
        total_duration_weeks=7,
        total_cost_eur=25_000,
    )


class _FakeWrapper:
    primary_model = "test-model"


class FakeService:
    def __init__(self) -> None:
        self.llm_wrapper = _FakeWrapper()
        self.invalidated: list = []

    def invalidate_caches(self, request) -> None:
        self.invalidated.append(request)

    def estimate(self, request) -> EstimationResponse:
        return EstimationResponse(
            result=_canned(),
            prompt_version="v1",
            cached=False,
            usage=LlmUsage(
                input_tokens=1200,
                output_tokens=350,
                total_tokens=1550,
                cost_usd=0.0125,
                latency_ms=4200,
                finish_reason="stop",
            ),
        )


@pytest.fixture
def fake_service():
    svc = FakeService()
    app.dependency_overrides[get_estimation_service] = lambda: svc
    yield svc
    app.dependency_overrides.pop(get_estimation_service, None)


# --- CRUD -------------------------------------------------------------------


def test_create_starts_in_editing(client: TestClient, sqlite_db) -> None:
    r = client.post("/api/v1/estimations", json={"title": "My estimate"})
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "editing"
    assert body["title"] == "My estimate"
    assert body["result"] is None


def test_list_returns_created(client: TestClient, sqlite_db) -> None:
    eid = client.post("/api/v1/estimations", json={"title": "A"}).json()["id"]
    rows = client.get("/api/v1/estimations").json()
    assert any(row["id"] == eid and row["status"] == "editing" for row in rows)


def test_get_404_for_unknown(client: TestClient, sqlite_db) -> None:
    assert client.get("/api/v1/estimations/does-not-exist").status_code == 404


def test_patch_updates_fields(client: TestClient, sqlite_db) -> None:
    eid = client.post("/api/v1/estimations", json={"title": "t"}).json()["id"]
    r = client.patch(
        f"/api/v1/estimations/{eid}",
        json={"title": "t2", "description": "x" * 40, "detail_level": "detailed"},
    )
    body = r.json()
    assert body["title"] == "t2"
    assert body["description"] == "x" * 40
    assert body["detail_level"] == "detailed"


def test_delete_then_404(client: TestClient, sqlite_db) -> None:
    eid = client.post("/api/v1/estimations", json={"title": "t"}).json()["id"]
    assert client.delete(f"/api/v1/estimations/{eid}").status_code == 204
    assert client.get(f"/api/v1/estimations/{eid}").status_code == 404


# --- Run lifecycle ----------------------------------------------------------


def test_run_finishes_and_stores_result(
    client: TestClient, sqlite_db, fake_service: FakeService
) -> None:
    eid = client.post(
        "/api/v1/estimations", json={"title": "t", "description": LONG_DESC}
    ).json()["id"]
    r = client.post(f"/api/v1/estimations/{eid}/run")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "finished"
    assert body["result"]["total_cost_eur"] == 25_000
    assert body["model"] == "test-model"
    assert body["provider"] == "unknown"
    assert body["input_tokens"] == 1200
    assert body["output_tokens"] == 350
    assert body["total_tokens"] == 1550
    assert body["cost_usd"] == 0.0125
    assert body["finish_reason"] == "stop"
    assert body["latency_ms"] == 4200


def test_run_with_short_description_sets_invalid_input_error(
    client: TestClient, sqlite_db, fake_service: FakeService
) -> None:
    eid = client.post(
        "/api/v1/estimations", json={"title": "t", "description": "short"}
    ).json()["id"]
    body = client.post(f"/api/v1/estimations/{eid}/run").json()
    assert body["status"] == "error"
    assert body["error_reason"] == "invalid_input"


def test_reestimate_invalidates_cache(
    client: TestClient, sqlite_db, fake_service: FakeService
) -> None:
    eid = client.post(
        "/api/v1/estimations", json={"title": "t", "description": LONG_DESC}
    ).json()["id"]
    client.post(f"/api/v1/estimations/{eid}/run")
    assert fake_service.invalidated == []
    r = client.post(f"/api/v1/estimations/{eid}/run", params={"reestimate": "true"})
    assert r.json()["status"] == "finished"
    assert len(fake_service.invalidated) == 1


def test_run_guardrail_violation_sets_error(client: TestClient, sqlite_db) -> None:
    class GuardrailService:
        llm_wrapper = _FakeWrapper()

        def invalidate_caches(self, request) -> None:  # pragma: no cover
            pass

        def estimate(self, request):
            raise InputGuardrailViolation("Email detected", reason="pii")

    app.dependency_overrides[get_estimation_service] = lambda: GuardrailService()
    try:
        eid = client.post(
            "/api/v1/estimations", json={"title": "t", "description": LONG_DESC}
        ).json()["id"]
        body = client.post(f"/api/v1/estimations/{eid}/run").json()
        assert body["status"] == "error"
        assert body["error_reason"] == "pii"
        assert body["error_message"] == "Email detected"
    finally:
        app.dependency_overrides.pop(get_estimation_service, None)
