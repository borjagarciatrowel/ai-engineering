import json
from unittest.mock import patch

from fastapi.testclient import TestClient


VALID_TRANSCRIPTION = (
    "We need to build a mobile app for a restaurant. It should have a menu page, "
    "cart, checkout flow with Stripe, and an admin panel to manage dishes. "
    "The tech stack should be React Native and Node.js. Timeline is 3 months."
)


def _fake_stream(transcription: str):
    yield json.dumps({"t": "Here "}).encode() + b"\n"
    yield json.dumps({"t": "is your estimation."}).encode() + b"\n"
    yield json.dumps({
        "done": True,
        "model": "gpt-test",
        "provider": "openai",
        "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
    }).encode() + b"\n"


def test_stream_endpoint_returns_ndjson(client: TestClient) -> None:
    with patch("app.routers.estimations.generate_stream", side_effect=_fake_stream):
        with client.stream("POST", "/api/v1/estimate/stream", json={"transcription": VALID_TRANSCRIPTION}) as response:
            assert response.status_code == 200
            assert "ndjson" in response.headers["content-type"]
            lines = [line for line in response.iter_lines() if line]

    assert len(lines) == 3
    first = json.loads(lines[0])
    assert first == {"t": "Here "}
    last = json.loads(lines[-1])
    assert last["done"] is True
    assert last["model"] == "gpt-test"
    assert last["usage"]["total_tokens"] == 30


def test_stream_endpoint_rejects_short_transcription(client: TestClient) -> None:
    # Exactly 49 chars — one below min_length=50 — must fail
    too_short = "a" * 49
    response = client.post("/api/v1/estimate/stream", json={"transcription": too_short})
    assert response.status_code == 422

    # Exactly 50 chars — at the boundary — schema accepts it (LLM call mocked out)
    at_boundary = "a" * 50
    with patch("app.routers.estimations.generate_stream", side_effect=_fake_stream):
        with client.stream("POST", "/api/v1/estimate/stream", json={"transcription": at_boundary}) as response:
            assert response.status_code == 200


def test_stream_endpoint_handles_llm_error(client: TestClient) -> None:
    from app.services.llm_service import LLMServiceError

    def failing_stream(transcription: str):
        raise LLMServiceError("provider down")
        yield  # make it a generator

    with patch("app.routers.estimations.generate_stream", side_effect=failing_stream):
        with client.stream("POST", "/api/v1/estimate/stream", json={"transcription": VALID_TRANSCRIPTION}) as response:
            assert response.status_code == 200
            lines = [line for line in response.iter_lines() if line]

    assert len(lines) == 1
    error_chunk = json.loads(lines[0])
    assert "error" in error_chunk
    assert "provider down" in error_chunk["error"]
