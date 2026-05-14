import asyncio
import json

import structlog
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.prompts.loader import render_estimation_prompt
from app.schemas.estimation import EstimationRequest, EstimationResponse, TokenUsage
from app.services.llm_service import (
    LLMServiceError,
    estimation,
    stream_estimation,
)

log = structlog.get_logger()

router = APIRouter(prefix="/api/v1", tags=["estimations"])


@router.post("/estimate", response_model=EstimationResponse)
async def create_estimation(
    request: EstimationRequest,
    prompt_version: str = Query("v1", description="Prompt template version"),
) -> EstimationResponse:
    """Render typed prompts via Jinja2 and return a free-text estimation."""
    system, user = render_estimation_prompt(request, version=prompt_version)
    try:
        result = estimation(system, user)
    except LLMServiceError as exc:
        log.error("estimation_endpoint_error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))

    return EstimationResponse(
        text=result["estimation"],
        prompt_version=prompt_version,
        model=result["model"],
        provider=result["provider"],
        usage=TokenUsage(**result["usage"]),
    )


@router.post("/estimate/stream")
async def stream_estimation_endpoint(
    request: EstimationRequest,
    prompt_version: str = Query("v1", description="Prompt template version"),
) -> StreamingResponse:
    """Stream a software estimation as NDJSON (one JSON object per line)."""
    system, user = render_estimation_prompt(request, version=prompt_version)

    async def _safe_stream():
        try:
            yield json.dumps({"prompt_version": prompt_version}).encode() + b"\n"
            await asyncio.sleep(0)
            for chunk in stream_estimation(system, user):
                yield chunk
                await asyncio.sleep(0)
        except LLMServiceError as exc:
            log.error("stream_endpoint_error", error=str(exc))
            yield json.dumps({"error": str(exc)}).encode() + b"\n"

    return StreamingResponse(_safe_stream(), media_type="application/x-ndjson")
