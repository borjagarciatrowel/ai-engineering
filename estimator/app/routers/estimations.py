import asyncio
import json

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.schemas.estimation import EstimationRequest, EstimationResponse
from app.services.llm_service import LLMServiceError, generate_estimation, stream_estimation as generate_stream

log = structlog.get_logger()

router = APIRouter(prefix="/api/v1", tags=["estimations"])


@router.post("/estimate", response_model=EstimationResponse)
async def create_estimation(request: EstimationRequest) -> EstimationResponse:
    """Receive a meeting transcription and return a software project estimation."""
    try:
        result = generate_estimation(request.transcription)
    except LLMServiceError as exc:
        log.error("estimation_endpoint_error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))

    return EstimationResponse(**result)


@router.post("/estimate/stream")
async def stream_estimation_endpoint(request: EstimationRequest) -> StreamingResponse:
    """Stream a software estimation as NDJSON (one JSON object per line)."""

    async def _safe_stream():
        try:
            for chunk in generate_stream(request.transcription):
                yield chunk
                await asyncio.sleep(0)  # flush write buffer before next blocking SDK call
        except LLMServiceError as exc:
            log.error("stream_endpoint_error", error=str(exc))
            yield json.dumps({"error": str(exc)}).encode() + b"\n"

    return StreamingResponse(_safe_stream(), media_type="application/x-ndjson")
