"""Integration test for POST /sessions/{id}/estimate-acb.

DB-backed (our persistence deviation): the session store persists to sqlite
via the ``sqlite_db`` override, so we inspect the persisted turn by reloading
the row through a fresh ``DbSessionStore``, not a process dict. Uses the shared
``FakeLLMWrapper`` from conftest, extended with a factory returning a canned
``CriticFeedback`` so the Boss runs deterministically.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.dependencies import (
    get_estimation_service,
    get_llm_wrapper,
    get_openai_client,
)
from app.main import app
from app.schemas.critic import CriticFeedback, CriticIssue
from app.services.estimation import EstimationService
from app.sessions.store import DbSessionStore
from tests.conftest import FakeLLMWrapper


VALID_FORM = {
    "transcript": "We need to estimate Nimbus, a CRM with React and Postgres for the sales team.",
    "project_type": "web_saas",
    "detail_level": "medium",
    "output_format": "phases_table",
}


@pytest.fixture
def acb_client(sqlite_db, fake_wrapper: FakeLLMWrapper):
    """Same wiring as conftest.conversational_client, with ``boss_max_iterations=2``.

    ``get_session_store`` is NOT overridden: it depends on ``get_db``, which the
    ``sqlite_db`` fixture already points at the in-memory database. Yields
    ``(client, session_factory)`` so a test can reload the persisted row."""
    service = EstimationService(
        llm_wrapper=fake_wrapper,
        exact_cache=None,
        semantic_cache=None,
        openai_client=None,
        metadata_extractor_model="gpt-4o-mini",
        boss_max_iterations=2,
    )
    app.dependency_overrides[get_estimation_service] = lambda: service
    app.dependency_overrides[get_llm_wrapper] = lambda: fake_wrapper
    app.dependency_overrides[get_openai_client] = lambda: None
    with TestClient(app) as c:
        yield c, sqlite_db
    for dep in (get_estimation_service, get_llm_wrapper, get_openai_client):
        app.dependency_overrides.pop(dep, None)


def _register_critic_accept(fake_wrapper: FakeLLMWrapper) -> None:
    fake_wrapper.register_response_for(
        CriticFeedback,
        lambda: CriticFeedback(verdict="accept", issues=[], confidence_in_review=90),
    )


def test_acb_endpoint_accepts_first_pass(
    acb_client, fake_wrapper: FakeLLMWrapper
) -> None:
    client, _session_factory = acb_client
    fake_wrapper.add_turn()
    _register_critic_accept(fake_wrapper)

    session_id = client.post("/sessions").json()["session_id"]

    response = client.post(f"/sessions/{session_id}/estimate-acb", data=VALID_FORM)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["prompt_version"] == "v3"
    assert body["cached"] is False
    assert "acb" in body
    assert body["acb"]["final_decision"] == "accept"
    assert body["acb"]["iterations_run"] == 1
    assert body["acb"]["iterations"][0]["critic_verdict"] == "accept"


def test_acb_endpoint_synthesizes_after_persistent_issues(
    acb_client, fake_wrapper: FakeLLMWrapper
) -> None:
    client, _session_factory = acb_client
    fake_wrapper.add_turn()

    fake_wrapper.register_response_for(
        CriticFeedback,
        lambda: CriticFeedback(
            verdict="needs_iteration",
            issues=[
                CriticIssue(
                    category="math_error",
                    severity="critical",
                    field_path="total_cost_eur",
                    description="sum mismatch in the totals",
                    suggested_fix="recompute the sum",
                )
            ],
            confidence_in_review=80,
        ),
    )

    session_id = client.post("/sessions").json()["session_id"]
    response = client.post(f"/sessions/{session_id}/estimate-acb", data=VALID_FORM)
    assert response.status_code == 200, response.text
    body = response.json()

    # The Critic never accepts → Boss exhausts the budget and synthesizes.
    # The synthesize policy now preserves the actor's last draft and prepends
    # the open caveats; it does NOT zero the totals or emit "Out of scope:".
    assert body["acb"]["final_decision"] == "synthesize"
    assert body["acb"]["iterations_run"] == 2
    assert body["result"]["summary"].startswith("⚠ Open caveats")
    assert "math_error" in body["result"]["summary"]
    assert body["result"]["total_cost_eur"] > 0
    # Confidence is reduced (floored at 30, never below LOW_CONFIDENCE_THRESHOLD).
    assert body["result"]["confidence_pct"] >= 30


def test_acb_endpoint_persists_only_final_result(
    acb_client, fake_wrapper: FakeLLMWrapper
) -> None:
    client, session_factory = acb_client
    fake_wrapper.add_turn()
    _register_critic_accept(fake_wrapper)

    session_id = client.post("/sessions").json()["session_id"]
    client.post(f"/sessions/{session_id}/estimate-acb", data=VALID_FORM)

    session = DbSessionStore(session_factory()).get_or_404(session_id)
    # Exactly one turn (user + assistant) lands in the history regardless of
    # how many drafts the Boss ran internally.
    assert len(session.history.messages) == 2
    assert session.history.messages[0].role == "user"
    assert session.history.messages[1].role == "assistant"


def test_acb_endpoint_404_for_unknown_session(acb_client) -> None:
    client, _session_factory = acb_client
    r = client.post("/sessions/does-not-exist/estimate-acb", data=VALID_FORM)
    assert r.status_code == 404
    assert r.json()["detail"] == "session_not_found"
