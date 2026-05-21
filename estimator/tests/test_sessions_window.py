"""Integration test: the sliding window caps how much history reaches the LLM.

DB-backed: the session store persists to sqlite (via the ``sqlite_db`` override),
so we inspect the bounded history by reloading the row, not a process dict.
"""

from __future__ import annotations

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from app.db import get_db
from app.dependencies import (
    get_estimation_service,
    get_llm_wrapper,
    get_openai_client,
    get_session_store,
)
from app.main import app
from app.services.estimation import EstimationService
from app.sessions.store import DbSessionStore
from tests.conftest import FakeLLMWrapper

VALID_FORM = {
    "transcript": "Turn N — refining the scope of the CRM project for the sales team.",
    "project_type": "web_saas",
    "detail_level": "medium",
    "output_format": "phases_table",
}


@pytest.fixture
def small_window_client(sqlite_db, fake_wrapper: FakeLLMWrapper):
    """Same wiring as conversational_client, but ``max_turns=3``."""
    service = EstimationService(
        llm_wrapper=fake_wrapper,
        exact_cache=None,
        semantic_cache=None,
        openai_client=None,
        metadata_extractor_model="gpt-4o-mini",
    )

    def _small_store(db=Depends(get_db)) -> DbSessionStore:
        return DbSessionStore(db, max_turns=3)

    app.dependency_overrides[get_estimation_service] = lambda: service
    app.dependency_overrides[get_llm_wrapper] = lambda: fake_wrapper
    app.dependency_overrides[get_openai_client] = lambda: None
    app.dependency_overrides[get_session_store] = _small_store
    with TestClient(app) as c:
        yield c, sqlite_db
    for dep in (
        get_estimation_service,
        get_llm_wrapper,
        get_openai_client,
        get_session_store,
    ):
        app.dependency_overrides.pop(dep, None)


def test_eight_turns_never_exceed_window(
    small_window_client, fake_wrapper: FakeLLMWrapper
) -> None:
    client, session_factory = small_window_client

    session_id = client.post("/sessions").json()["session_id"]

    for n in range(8):
        body = {**VALID_FORM, "transcript": f"Turn {n}: refine and add scope details here for clarity."}
        response = client.post(f"/sessions/{session_id}/estimate", data=body)
        assert response.status_code == 200, response.text

    # 8 turns × 2 calls (estimation + extractor) = 16 chat_calls
    assert len(fake_wrapper.chat_calls) == 16

    # Inspect only the estimation calls (even indexes).
    estimation_calls = fake_wrapper.chat_calls[::2]
    assert len(estimation_calls) == 8

    # max_turns=3 → at most 3 user/assistant pairs from history,
    # plus 1 system + 1 current user. Cap = 1 + 6 + 1 = 8.
    for idx, call in enumerate(estimation_calls):
        assert len(call["messages"]) <= 8, (
            f"Estimation call {idx} sent {len(call['messages'])} messages; "
            "the sliding window should cap it at 8."
        )

    # And the persisted history itself stays bounded:
    session = DbSessionStore(session_factory()).get_or_404(session_id)
    assert len(session.history.messages) <= 3 * 2


def test_history_keeps_most_recent_pairs(
    small_window_client, fake_wrapper: FakeLLMWrapper
) -> None:
    client, session_factory = small_window_client
    session_id = client.post("/sessions").json()["session_id"]

    for n in range(5):
        client.post(
            f"/sessions/{session_id}/estimate",
            data={**VALID_FORM, "transcript": f"Turn {n}: refining scope details here for clarity."},
        )

    session = DbSessionStore(session_factory()).get_or_404(session_id)
    # max_turns=3 keeps the last 3 pairs (turns 2, 3, 4).
    user_messages = [m for m in session.history.messages if m.role == "user"]
    assert len(user_messages) == 3
    assert "Turn 2" in user_messages[0].content
    assert "Turn 4" in user_messages[-1].content
