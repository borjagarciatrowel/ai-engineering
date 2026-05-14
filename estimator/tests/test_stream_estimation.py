import json
from unittest.mock import patch

from fastapi.testclient import TestClient


VALID_REQUEST = {
    "description": (
        "We need to build a mobile app for a restaurant. It should have a menu page, "
        "cart, checkout flow with Stripe, and an admin panel to manage dishes."
    ),
    "project_type": "mobile_app",
    "detail_level": "medium",
    "output_format": "phases_table",
}


def _fake_stream(system: str, user: str):
    yield json.dumps({"t": "Here "}).encode() + b"\n"
    yield json.dumps({"t": "is your estimation."}).encode() + b"\n"
    yield json.dumps({
        "done": True,
        "model": "gpt-test",
        "provider": "openai",
        "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
    }).encode() + b"\n"


def test_stream_endpoint_returns_ndjson(client: TestClient) -> None:
    with patch("app.routers.estimations.stream_estimation", side_effect=_fake_stream):
        with client.stream("POST", "/api/v1/estimate/stream", json=VALID_REQUEST) as response:
            assert response.status_code == 200
            assert "ndjson" in response.headers["content-type"]
            lines = [line for line in response.iter_lines() if line]

    # First line announces prompt_version, then 2 token chunks + done
    assert len(lines) == 4
    first = json.loads(lines[0])
    assert first == {"prompt_version": "v1"}

    last = json.loads(lines[-1])
    assert last["done"] is True
    assert last["model"] == "gpt-test"
    assert last["usage"]["total_tokens"] == 30


def test_stream_endpoint_rejects_short_description(client: TestClient) -> None:
    payload = {**VALID_REQUEST, "description": "a" * 19}
    response = client.post("/api/v1/estimate/stream", json=payload)
    assert response.status_code == 422


def test_stream_endpoint_rejects_invalid_enum(client: TestClient) -> None:
    payload = {**VALID_REQUEST, "project_type": "not_a_real_type"}
    response = client.post("/api/v1/estimate/stream", json=payload)
    assert response.status_code == 422


def test_stream_endpoint_handles_llm_error(client: TestClient) -> None:
    from app.services.llm_service import LLMServiceError

    def failing_stream(system: str, user: str):
        raise LLMServiceError("provider down")
        yield  # make it a generator

    with patch("app.routers.estimations.stream_estimation", side_effect=failing_stream):
        with client.stream("POST", "/api/v1/estimate/stream", json=VALID_REQUEST) as response:
            assert response.status_code == 200
            lines = [line for line in response.iter_lines() if line]

    # First line is prompt_version, second is the error chunk
    assert len(lines) == 2
    error_chunk = json.loads(lines[1])
    assert "error" in error_chunk
    assert "provider down" in error_chunk["error"]
