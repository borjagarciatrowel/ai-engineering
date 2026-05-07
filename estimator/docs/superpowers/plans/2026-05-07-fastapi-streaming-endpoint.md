# FastAPI Streaming Endpoint + Streamlit via httpx

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a streaming endpoint to FastAPI and refactor Streamlit to call it via httpx, removing all direct imports from `app.*`.

**Architecture:** FastAPI exposes `POST /api/v1/estimate/stream` returning NDJSON (one JSON object per line). Each line is either a text chunk `{"t": "..."}` or a final metadata event `{"done": true, "model": "...", "provider": "...", "usage": {...}}`. Streamlit consumes the stream via `httpx`, yields text for `st.write_stream`, and captures metadata from the final event via `st.session_state`.

**Tech Stack:** FastAPI, StreamingResponse, httpx (sync), structlog, OpenAI SDK, Anthropic SDK, Streamlit

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `app/services/llm_service.py` | Modify | Add `stream_estimation()` generator |
| `app/routers/estimations.py` | Modify | Add `/api/v1/estimate/stream` endpoint |
| `tests/test_stream_estimation.py` | Create | Test streaming endpoint |
| `streamlit_app.py` | Modify | Replace direct LLM calls with httpx |

---

### Task 1: Add `stream_estimation()` to `llm_service.py`

**Files:**
- Modify: `app/services/llm_service.py`

This adds a generator that yields NDJSON lines — text chunks first, metadata last.

- [ ] **Step 1: Add the streaming generator and helpers**

Append to `app/services/llm_service.py` after the existing `_call_anthropic` function:

```python
import json
from collections.abc import Generator


def stream_estimation(transcription: str) -> Generator[bytes, None, None]:
    """Stream a software estimation as NDJSON bytes.

    Each yielded line is either:
    - {"t": "<text chunk>"}  — partial text token
    - {"done": true, "model": "...", "provider": "...", "usage": {...}}  — final metadata
    """
    settings = get_settings()
    system_prompt = build_system_prompt()

    log.info("stream_estimation_start", provider=settings.LLM_PROVIDER, model=settings.LLM_MODEL)

    try:
        if settings.LLM_PROVIDER == "openai":
            yield from _stream_openai(system_prompt, transcription)
        else:
            yield from _stream_anthropic(system_prompt, transcription)
    except Exception as exc:
        log.error("stream_estimation_failed", error=str(exc), provider=settings.LLM_PROVIDER)
        raise LLMServiceError(f"LLM streaming failed: {exc}") from exc


def _stream_openai(system_prompt: str, transcription: str) -> Generator[bytes, None, None]:
    from openai import OpenAI

    settings = get_settings()
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    model_used = settings.LLM_MODEL
    usage_data: dict = {}

    stream = client.chat.completions.create(
        model=settings.LLM_MODEL,
        max_tokens=MAX_TOKENS,
        stream=True,
        stream_options={"include_usage": True},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": transcription},
        ],
    )

    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield json.dumps({"t": chunk.choices[0].delta.content}).encode() + b"\n"
        if chunk.model:
            model_used = chunk.model
        if chunk.usage:
            usage_data = {
                "input_tokens": chunk.usage.prompt_tokens,
                "output_tokens": chunk.usage.completion_tokens,
                "total_tokens": chunk.usage.total_tokens,
            }

    usage_data.setdefault("input_tokens", 0)
    usage_data.setdefault("output_tokens", 0)
    usage_data.setdefault("total_tokens", 0)

    yield json.dumps({
        "done": True,
        "model": model_used,
        "provider": "openai",
        "usage": usage_data,
    }).encode() + b"\n"


def _stream_anthropic(system_prompt: str, transcription: str) -> Generator[bytes, None, None]:
    from anthropic import Anthropic

    settings = get_settings()
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    with client.messages.stream(
        model=settings.LLM_MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": transcription}],
    ) as stream:
        for text in stream.text_stream:
            yield json.dumps({"t": text}).encode() + b"\n"

        msg = stream.get_final_message()
        yield json.dumps({
            "done": True,
            "model": msg.model,
            "provider": "anthropic",
            "usage": {
                "input_tokens": msg.usage.input_tokens,
                "output_tokens": msg.usage.output_tokens,
                "total_tokens": msg.usage.input_tokens + msg.usage.output_tokens,
            },
        }).encode() + b"\n"
```

- [ ] **Step 2: Verify imports at top of `llm_service.py`**

Confirm `import json` and `from collections.abc import Generator` are present. Add them at the top if missing — the file currently starts with `import structlog`.

- [ ] **Step 3: Commit**

```bash
git add app/services/llm_service.py
git commit -m "feat(llm): add stream_estimation() generator for NDJSON streaming"
```

---

### Task 2: Add `/api/v1/estimate/stream` endpoint

**Files:**
- Modify: `app/routers/estimations.py`

- [ ] **Step 1: Add the streaming endpoint**

In `app/routers/estimations.py`, add this import and endpoint:

```python
from fastapi.responses import StreamingResponse
```

Then add after the existing `create_estimation` function:

```python
@router.post("/estimate/stream")
async def stream_estimation_endpoint(request: EstimationRequest) -> StreamingResponse:
    """Stream a software estimation as NDJSON (one JSON object per line)."""
    try:
        generator = generate_stream(request.transcription)
    except LLMServiceError as exc:
        log.error("stream_endpoint_error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))

    return StreamingResponse(generator, media_type="application/x-ndjson")
```

Also update the import from `llm_service`:

```python
from app.services.llm_service import LLMServiceError, generate_estimation, stream_estimation as generate_stream
```

- [ ] **Step 2: Commit**

```bash
git add app/routers/estimations.py
git commit -m "feat(api): add POST /api/v1/estimate/stream NDJSON streaming endpoint"
```

---

### Task 3: Test the streaming endpoint

**Files:**
- Create: `tests/test_stream_estimation.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_stream_estimation.py`:

```python
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


VALID_TRANSCRIPTION = (
    "We need to build a mobile app for a restaurant. It should have a menu page, "
    "cart, checkout flow with Stripe, and an admin panel to manage dishes. "
    "The tech stack should be React Native and Node.js. Timeline is 3 months."
)


def _fake_stream(transcription: str):
    yield json.dumps({"t": "Here "}).encode() + b"\n"
    yield json.dumps({"t": "is "}).encode() + b"\n"
    yield json.dumps({"t": "your estimation."}).encode() + b"\n"
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

    assert len(lines) == 4
    first = json.loads(lines[0])
    assert first == {"t": "Here "}
    last = json.loads(lines[-1])
    assert last["done"] is True
    assert last["model"] == "gpt-test"
    assert last["usage"]["total_tokens"] == 30


def test_stream_endpoint_rejects_short_transcription(client: TestClient) -> None:
    response = client.post("/api/v1/estimate/stream", json={"transcription": "too short"})
    assert response.status_code == 422


def test_stream_endpoint_handles_llm_error(client: TestClient) -> None:
    from app.services.llm_service import LLMServiceError

    def failing_stream(transcription: str):
        raise LLMServiceError("provider down")
        yield  # make it a generator

    with patch("app.routers.estimations.generate_stream", side_effect=failing_stream):
        response = client.post("/api/v1/estimate/stream", json={"transcription": VALID_TRANSCRIPTION})
    assert response.status_code == 500
```

- [ ] **Step 2: Run tests — expect failures**

```bash
pytest tests/test_stream_estimation.py -v
```

Expected: FAIL — `generate_stream` not yet importable (Task 2 must be done first).

> If Task 2 is done, expected: PASS on `test_stream_endpoint_rejects_short_transcription`, FAIL on the streaming tests until mocks are wired.

- [ ] **Step 3: Run full test suite to check no regressions**

```bash
pytest -v
```

Expected: all pre-existing tests PASS, new streaming tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_stream_estimation.py
git commit -m "test(api): add streaming endpoint tests with NDJSON format verification"
```

---

### Task 4: Refactor `streamlit_app.py` to use httpx

**Files:**
- Modify: `streamlit_app.py`

- [ ] **Step 1: Add `httpx` to dependencies**

```bash
cd estimator && uv add httpx
```

Expected output: `httpx` added to `pyproject.toml` and `uv.lock`.

- [ ] **Step 2: Rewrite `streamlit_app.py`**

Replace the entire file contents with:

```python
import json
import os
import time

import httpx
import streamlit as st

BACKEND_URL = os.getenv("BACKEND_URL", "http://estimator:8000")

st.set_page_config(
    page_title="Estimador de Software",
    page_icon="🏗️",
    layout="wide",
)

if "messages" not in st.session_state:
    st.session_state.messages = []
if "last_metrics" not in st.session_state:
    st.session_state.last_metrics = None


def stream_from_api(transcription: str):
    """Call FastAPI /api/v1/estimate/stream and yield text tokens.

    Stores final metadata in st.session_state._pending_metrics.
    """
    with httpx.stream(
        "POST",
        f"{BACKEND_URL}/api/v1/estimate/stream",
        json={"transcription": transcription},
        timeout=120,
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line:
                continue
            chunk = json.loads(line)
            if "t" in chunk:
                yield chunk["t"]
            elif chunk.get("done"):
                st.session_state._pending_metrics = {
                    "model": chunk.get("model", "unknown"),
                    "input_tokens": chunk.get("usage", {}).get("input_tokens", 0),
                    "output_tokens": chunk.get("usage", {}).get("output_tokens", 0),
                }


# Sidebar
with st.sidebar:
    st.header("📊 Métricas")

    if st.session_state.last_metrics:
        m = st.session_state.last_metrics
        st.metric("Modelo", m["model"])
        col1, col2 = st.columns(2)
        col1.metric("Tokens entrada", m["input_tokens"])
        col2.metric("Tokens salida", m["output_tokens"])
        st.metric("Tiempo de respuesta", f"{m['response_time']:.2f}s")

    st.divider()
    if st.button("🗑️ Limpiar conversación", use_container_width=True):
        st.session_state.messages = []
        st.session_state.last_metrics = None
        st.rerun()


# Main chat
st.title("🏗️ Estimador de Software")
st.caption("Pega la transcripción de una reunión y obtén una estimación detallada del proyecto.")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("Pega aquí la transcripción de la reunión..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        start_time = time.time()
        full_response = st.write_stream(stream_from_api(prompt))
        response_time = time.time() - start_time

    st.session_state.messages.append({"role": "assistant", "content": full_response})

    pending = st.session_state.pop("_pending_metrics", {})
    st.session_state.last_metrics = {
        "model": pending.get("model", "unknown"),
        "input_tokens": pending.get("input_tokens", 0),
        "output_tokens": pending.get("output_tokens", 0),
        "response_time": response_time,
    }
    st.rerun()
```

- [ ] **Step 3: Add `BACKEND_URL` to docker-compose streamlit service**

In `docker-compose.yml`, under the `streamlit` service `environment:` section (add if not present):

```yaml
    environment:
      - BACKEND_URL=http://estimator:8000
```

- [ ] **Step 4: Verify Streamlit no longer imports from `app.*`**

```bash
grep "from app\." estimator/streamlit_app.py
```

Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add streamlit_app.py docker-compose.yml pyproject.toml uv.lock
git commit -m "refactor(streamlit): call FastAPI streaming endpoint via httpx, remove direct app imports"
```

---

### Task 5: Integration smoke test

- [ ] **Step 1: Build and start the stack**

```bash
docker compose up --build -d
```

- [ ] **Step 2: Verify backend streaming endpoint directly**

```bash
curl -N -X POST http://localhost:8000/api/v1/estimate/stream \
  -H "Content-Type: application/json" \
  -d '{"transcription": "We need a restaurant ordering app with React Native, Node.js backend, Stripe payments, and an admin panel. Timeline 3 months, team of 4."}' \
  | head -20
```

Expected: NDJSON lines starting with `{"t": "..."}` and ending with `{"done": true, ...}`.

- [ ] **Step 3: Open Streamlit at http://localhost:8501 and paste a transcription**

Expected: response streams token by token, sidebar metrics appear after completion.

- [ ] **Step 4: Final commit if any docker-compose tweaks were needed**

```bash
git add -p
git commit -m "chore: finalize docker-compose config for streaming integration"
```
