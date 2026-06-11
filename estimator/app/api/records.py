"""Persisted-estimation CRUD + lifecycle.

Routes (prefix /api/v1/estimations):
    GET    ""              list (lightweight rows, newest first)
    POST   ""              create (status=editing)
    GET    "/{eid}"        full record
    PATCH  "/{eid}"        update editable fields
    POST   "/{eid}/run"    run the pipeline; ?reestimate=true clears caches first
    DELETE "/{eid}"        delete

The run handler maps pipeline outcomes onto the lifecycle:
    success                → finished (result + model metadata stored)
    InputGuardrailViolation→ error  (reason = moderation|prompt_injection|pii)
    invalid request        → error  (reason = invalid_input)
    anything else          → error  (reason = upstream_llm)
"""

from __future__ import annotations

import time

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.foundation.persistence.db import get_db
from app.foundation.persistence.db_models import Estimation
from app.dependencies import get_estimation_service
from app.foundation.guardrails.input import InputGuardrailViolation
from app.domain.schemas.estimation import EstimationRequest
from app.domain.schemas.record import (
    EstimationCreate,
    EstimationListItem,
    EstimationRecord,
    EstimationUpdate,
)
from app.domain.estimation_service import EstimationService

log = structlog.get_logger()

router = APIRouter(prefix="/api/v1/estimations", tags=["estimations-crud"])


def _get_or_404(db: Session, eid: str) -> Estimation:
    rec = db.get(Estimation, eid)
    if rec is None:
        raise HTTPException(status_code=404, detail="Estimation not found")
    return rec


def _request_from(rec: Estimation) -> EstimationRequest:
    """Build the typed pipeline request from a stored record (validates length/enums)."""
    return EstimationRequest(
        description=rec.description,
        project_type=rec.project_type,
        detail_level=rec.detail_level,
        output_format=rec.output_format,
    )


def _provider_for(model: str) -> str:
    name = model.split("/", 1)[-1].lower()
    if name.startswith("claude"):
        return "anthropic"
    if name.startswith(("gpt", "o1", "o3")):
        return "openai"
    return "unknown"


@router.get("", response_model=list[EstimationListItem])
def list_estimations(db: Session = Depends(get_db)) -> list[Estimation]:
    return list(
        db.execute(select(Estimation).order_by(Estimation.updated_at.desc())).scalars().all()
    )


@router.post("", response_model=EstimationRecord, status_code=201)
def create_estimation(
    payload: EstimationCreate, db: Session = Depends(get_db)
) -> Estimation:
    rec = Estimation(**payload.model_dump(mode="json"), status="editing")
    db.add(rec)
    db.commit()
    db.refresh(rec)
    log.info("estimation_record_created", id=rec.id, title=rec.title)
    return rec


@router.get("/{eid}", response_model=EstimationRecord)
def get_estimation(eid: str, db: Session = Depends(get_db)) -> Estimation:
    return _get_or_404(db, eid)


@router.patch("/{eid}", response_model=EstimationRecord)
def update_estimation(
    eid: str, payload: EstimationUpdate, db: Session = Depends(get_db)
) -> Estimation:
    rec = _get_or_404(db, eid)
    changes = payload.model_dump(mode="json", exclude_unset=True)
    for key, value in changes.items():
        setattr(rec, key, value)
    db.commit()
    db.refresh(rec)
    return rec


@router.delete("/{eid}", status_code=204)
def delete_estimation(eid: str, db: Session = Depends(get_db)) -> None:
    rec = _get_or_404(db, eid)
    db.delete(rec)
    db.commit()
    log.info("estimation_record_deleted", id=eid)


@router.post("/{eid}/run", response_model=EstimationRecord)
def run_estimation(
    eid: str,
    reestimate: bool = False,
    db: Session = Depends(get_db),
    service: EstimationService = Depends(get_estimation_service),
) -> Estimation:
    rec = _get_or_404(db, eid)

    # Build + validate the request up front so a too-short description fails fast.
    try:
        request = _request_from(rec)
    except ValidationError as exc:
        rec.status = "error"
        rec.error_reason = "invalid_input"
        rec.error_message = "; ".join(e["msg"] for e in exc.errors())[:1000]
        db.commit()
        db.refresh(rec)
        return rec

    # Mark running so a concurrent list view shows the in-flight state.
    rec.status = "running"
    rec.error_reason = None
    rec.error_message = None
    db.commit()

    if reestimate:
        # Drop cached answers so the prompt change actually re-runs the LLM.
        service.invalidate_caches(request)

    t0 = time.perf_counter()
    try:
        response = service.estimate(request)
    except InputGuardrailViolation as exc:
        rec.status = "error"
        rec.error_reason = exc.reason
        rec.error_message = exc.message
        db.commit()
        db.refresh(rec)
        log.info("estimation_run_blocked", id=eid, reason=exc.reason)
        return rec
    except Exception as exc:  # noqa: BLE001 — surface any upstream/LLM failure as error state
        rec.status = "error"
        rec.error_reason = "upstream_llm"
        rec.error_message = str(exc)[:1000]
        db.commit()
        db.refresh(rec)
        log.error("estimation_run_failed", id=eid, error_type=type(exc).__name__)
        return rec

    usage = response.usage
    rec.result = response.result.model_dump(mode="json")
    rec.prompt_version = response.prompt_version
    rec.cached = response.cached
    rec.model = service.llm_wrapper.primary_model
    rec.provider = _provider_for(service.llm_wrapper.primary_model)
    rec.input_tokens = usage.input_tokens if usage else None
    rec.output_tokens = usage.output_tokens if usage else None
    rec.total_tokens = usage.total_tokens if usage else None
    rec.cost_usd = usage.cost_usd if usage else None
    rec.finish_reason = usage.finish_reason if usage else None
    rec.latency_ms = (
        usage.latency_ms
        if usage and usage.latency_ms is not None
        else int((time.perf_counter() - t0) * 1000)
    )
    rec.status = "finished"
    db.commit()
    db.refresh(rec)
    log.info(
        "estimation_run_finished",
        id=eid,
        cached=rec.cached,
        latency_ms=rec.latency_ms,
        total_tokens=rec.total_tokens,
        cost_usd=rec.cost_usd,
    )
    return rec
