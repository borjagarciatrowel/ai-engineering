"""Integration test: a multi-turn session accumulates ProjectMetadata.

The fake wrapper returns canned EstimationResult / ProjectMetadata pairs, so the
test runs offline and deterministically. State is persisted to sqlite between
turns, then read back through ``GET /sessions/{id}``.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.sessions.models import ProjectMetadata
from tests.conftest import FakeLLMWrapper, make_canned_result

VALID_FORM = {
    "transcript": "We want a CRM called Nimbus built with React and Postgres for the sales team.",
    "project_type": "web_saas",
    "detail_level": "medium",
    "output_format": "phases_table",
}


def test_two_turns_accumulate_metadata(
    conversational_client: tuple[TestClient, object], fake_wrapper: FakeLLMWrapper
) -> None:
    client, _factory = conversational_client
    fake_wrapper.scripted = [
        (
            make_canned_result(),
            ProjectMetadata(
                project_name="Nimbus",
                assumed_team_size=3,
                mentioned_technologies=["React", "Postgres"],
                agreed_scope="Phase 1 MVP CRM for sales team.",
            ),
        ),
        (
            make_canned_result(),
            ProjectMetadata(
                project_name=None,
                assumed_team_size=None,
                mentioned_technologies=["Stripe"],
                agreed_scope="Phase 1 MVP CRM with billing.",
            ),
        ),
    ]

    create = client.post("/sessions")
    assert create.status_code == 201
    session_id = create.json()["session_id"]

    # Turn 1
    r1 = client.post(f"/sessions/{session_id}/estimate", data=VALID_FORM)
    assert r1.status_code == 200, r1.text
    body = r1.json()
    assert body["prompt_version"] == "v2"
    assert body["cached"] is False
    assert body["result"]["total_cost_eur"] == 25_000

    # Turn 2 — adds billing
    follow_up = {**VALID_FORM, "transcript": "Now add Stripe-based billing on top."}
    r2 = client.post(f"/sessions/{session_id}/estimate", data=follow_up)
    assert r2.status_code == 200, r2.text

    # The persisted session should reflect the merged metadata.
    info = client.get(f"/sessions/{session_id}").json()
    assert info["metadata"]["project_name"] == "Nimbus"
    assert info["metadata"]["assumed_team_size"] == 3
    assert sorted(info["metadata"]["mentioned_technologies"]) == sorted(
        ["React", "Postgres", "Stripe"]
    )
    assert "billing" in info["metadata"]["agreed_scope"].lower()
    # Two turns persisted → 4 messages in the history.
    assert info["message_count"] == 4


def test_conversational_turn_appears_in_grid(
    conversational_client: tuple[TestClient, object], fake_wrapper: FakeLLMWrapper
) -> None:
    """A conversational turn is mirrored into the estimations grid (one row per
    session, refreshed each turn)."""
    client, _ = conversational_client
    fake_wrapper.scripted = [
        (make_canned_result(), ProjectMetadata(project_name="Nimbus")),
        (make_canned_result(), ProjectMetadata()),
    ]
    sid = client.post("/sessions").json()["session_id"]

    r = client.post(f"/sessions/{sid}/estimate", data=VALID_FORM)
    assert r.status_code == 200, r.text

    grid = client.get("/api/v1/estimations").json()
    nimbus = [row for row in grid if row["title"] == "Nimbus"]
    assert len(nimbus) == 1
    assert nimbus[0]["status"] == "finished"

    # A second turn updates the SAME row, it does not create a new one.
    client.post(
        f"/sessions/{sid}/estimate",
        data={**VALID_FORM, "transcript": "Now add Stripe billing to the CRM project."},
    )
    grid2 = client.get("/api/v1/estimations").json()
    assert len([row for row in grid2 if row["title"] == "Nimbus"]) == 1


def test_conversation_endpoint_returns_turns(
    conversational_client: tuple[TestClient, object], fake_wrapper: FakeLLMWrapper
) -> None:
    """GET /sessions/{id}/conversation returns the turn-by-turn history; the user
    turn stores the raw transcript (not the rendered prompt) for clean display."""
    client, _ = conversational_client
    fake_wrapper.add_turn()
    sid = client.post("/sessions").json()["session_id"]
    client.post(f"/sessions/{sid}/estimate", data=VALID_FORM)

    conv = client.get(f"/sessions/{sid}/conversation").json()
    assert len(conv["messages"]) == 2
    assert conv["messages"][0]["role"] == "user"
    assert conv["messages"][0]["content"] == VALID_FORM["transcript"]
    assert conv["messages"][1]["role"] == "assistant"


def test_mirrored_estimation_exposes_session_id(
    conversational_client: tuple[TestClient, object], fake_wrapper: FakeLLMWrapper
) -> None:
    """The grid row mirrored from a turn carries session_id so the detail view can
    load the conversation."""
    client, _ = conversational_client
    fake_wrapper.scripted = [(make_canned_result(), ProjectMetadata(project_name="Nimbus"))]
    sid = client.post("/sessions").json()["session_id"]
    client.post(f"/sessions/{sid}/estimate", data=VALID_FORM)

    eid = next(r["id"] for r in client.get("/api/v1/estimations").json() if r["title"] == "Nimbus")
    record = client.get(f"/api/v1/estimations/{eid}").json()
    assert record["session_id"] == sid


def test_session_404_returns_not_found(
    conversational_client: tuple[TestClient, object]
) -> None:
    client, _ = conversational_client
    r = client.post("/sessions/does-not-exist/estimate", data=VALID_FORM)
    assert r.status_code == 404
    assert r.json()["detail"] == "session_not_found"


def test_create_session_returns_unique_ids(
    conversational_client: tuple[TestClient, object]
) -> None:
    client, _ = conversational_client
    a = client.post("/sessions").json()["session_id"]
    b = client.post("/sessions").json()["session_id"]
    assert a != b
