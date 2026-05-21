"""Conversational endpoints for Session 5.

Three endpoints:

- ``POST /sessions``                       — create a new session, return its UUID.
- ``POST /sessions/{session_id}/estimate`` — multi-turn estimation. Accepts
  ``multipart/form-data`` with the transcript plus optional file attachments
  (PDF or DOCX). Attachment text is extracted locally (Camino B) and
  concatenated into the transcript before the LLM is invoked.
- ``GET  /sessions/{session_id}``          — debug view of the session
  (metadata + history length). Used by the client's metadata panel.

Persistence note: the session store is Postgres-backed (``DbSessionStore``).
The service mutates the loaded ``Session`` in place (appends the turn, refreshes
metadata); the router then calls ``store.save(session)`` to flush those changes
to the ``chat_sessions`` row. This is the project deviation from the brief's
in-memory dict.

Error mapping mirrors the v1 router:
- ``InputGuardrailViolation`` → 400 with ``{reason, message}``.
- ``UnsupportedAttachmentError`` → 415.
- ``AttachmentExtractionError``  → 422.
- ``SessionNotFoundError`` → 404.
- anything else → 502.
"""

from __future__ import annotations

from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as SaSession

from app.attachments.extractor import (
    AttachmentExtractionError,
    UnsupportedAttachmentError,
    enrich_transcript,
    extract_text,
)
from app.config import get_settings
from app.db import get_db
from app.db_models import Estimation
from app.dependencies import get_estimation_service, get_session_store
from app.guardrails.input import InputGuardrailViolation
from app.schemas.estimation import (
    DetailLevel,
    EstimationResponse,
    OutputFormat,
    ProjectType,
)
from app.services.estimation import EstimationService
from app.sessions.models import ProjectMetadata, Session
from app.sessions.store import DbSessionStore, SessionNotFoundError

log = structlog.get_logger()

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _provider_for(model: str) -> str:
    name = model.split("/", 1)[-1].lower()
    if name.startswith("claude"):
        return "anthropic"
    if name.startswith(("gpt", "o1", "o3")):
        return "openai"
    return "unknown"


def _mirror_turn_to_grid(
    db: SaSession,
    *,
    session: Session,
    transcript: str,
    project_type: ProjectType,
    detail_level: DetailLevel,
    output_format: OutputFormat,
    response: EstimationResponse,
    model: str,
) -> None:
    """Upsert one ``Estimation`` row per conversational session so the turn shows
    in the estimations grid. One row per session, refreshed every turn with the
    latest result + telemetry. Best-effort: a mirror failure must not break the
    conversational response (the source of truth is ``chat_sessions``)."""
    rec = (
        db.execute(select(Estimation).where(Estimation.session_id == session.session_id))
        .scalars()
        .first()
    )
    if rec is None:
        rec = Estimation(session_id=session.session_id)
        db.add(rec)

    rec.title = session.metadata.project_name or f"Conversación {session.session_id[:8]}"
    rec.status = "finished"
    rec.description = transcript
    rec.project_type = project_type.value
    rec.detail_level = detail_level.value
    rec.output_format = output_format.value
    rec.result = response.result.model_dump(mode="json")
    rec.prompt_version = response.prompt_version
    rec.cached = response.cached
    rec.model = model
    rec.provider = _provider_for(model)
    usage = response.usage
    rec.input_tokens = usage.input_tokens if usage else None
    rec.output_tokens = usage.output_tokens if usage else None
    rec.total_tokens = usage.total_tokens if usage else None
    rec.cost_usd = usage.cost_usd if usage else None
    rec.finish_reason = usage.finish_reason if usage else None
    rec.latency_ms = usage.latency_ms if usage else None
    rec.error_reason = None
    rec.error_message = None
    db.commit()


class CreateSessionResponse(BaseModel):
    session_id: str = Field(description="UUID identifier for the new conversational session.")
    estimation_id: str = Field(description="Id of the mirrored estimation row (the grid/detail entry).")


class SessionInfoResponse(BaseModel):
    session_id: str
    message_count: int
    max_turns: int
    metadata: ProjectMetadata


class ConversationMessage(BaseModel):
    role: str
    content: str
    created_at: datetime


class ConversationResponse(BaseModel):
    session_id: str
    max_turns: int
    metadata: ProjectMetadata
    messages: list[ConversationMessage]


@router.post("", response_model=CreateSessionResponse, status_code=201)
def create_session(
    store: DbSessionStore = Depends(get_session_store),
    db: SaSession = Depends(get_db),
) -> CreateSessionResponse:
    """Create a conversational session AND its mirrored estimation row.

    The estimation row starts ``editing`` (empty conversation); the first turn
    flips it to ``finished`` and fills the title from the extracted project name.
    Creating it up front gives the new conversation a grid entry and a stable
    detail URL (`/estimations/{id}`) immediately.
    """
    session = store.create()
    rec = Estimation(
        session_id=session.session_id,
        title="Nueva conversación",
        status="editing",
        description="",
        project_type="web_saas",
        detail_level="medium",
        output_format="phases_table",
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    log.info("session_created", session_id=session.session_id, estimation_id=rec.id)
    return CreateSessionResponse(session_id=session.session_id, estimation_id=rec.id)


@router.get("/{session_id}", response_model=SessionInfoResponse)
def get_session(
    session_id: str,
    store: DbSessionStore = Depends(get_session_store),
) -> SessionInfoResponse:
    try:
        session = store.get_or_404(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="session_not_found") from exc
    return SessionInfoResponse(
        session_id=session.session_id,
        message_count=len(session.history.messages),
        max_turns=session.history.max_turns,
        metadata=session.metadata,
    )


@router.get("/{session_id}/conversation", response_model=ConversationResponse)
def get_conversation(
    session_id: str,
    store: DbSessionStore = Depends(get_session_store),
) -> ConversationResponse:
    """Full turn-by-turn history of a session (used by the estimation detail view
    to show the conversation that produced a conversational estimation)."""
    try:
        session = store.get_or_404(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="session_not_found") from exc
    return ConversationResponse(
        session_id=session.session_id,
        max_turns=session.history.max_turns,
        metadata=session.metadata,
        messages=[
            ConversationMessage(role=m.role, content=m.content, created_at=m.created_at)
            for m in session.history.messages
        ],
    )


@router.post("/{session_id}/estimate", response_model=EstimationResponse)
async def estimate_in_session(
    session_id: str,
    transcript: str = Form(..., min_length=20, max_length=80_000),
    project_type: ProjectType = Form(...),
    detail_level: DetailLevel = Form(...),
    output_format: OutputFormat = Form(...),
    attachments: list[UploadFile] = File(default_factory=list),
    store: DbSessionStore = Depends(get_session_store),
    service: EstimationService = Depends(get_estimation_service),
    db: SaSession = Depends(get_db),
) -> EstimationResponse:
    try:
        session = store.get_or_404(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="session_not_found") from exc

    settings = get_settings()
    extracted: list[tuple[str, str]] = []
    for upload in attachments or []:
        if not upload.filename:
            continue
        content = await upload.read()
        try:
            text = extract_text(
                filename=upload.filename,
                content=content,
                max_chars=settings.MAX_ATTACHMENT_CHARS,
            )
        except UnsupportedAttachmentError as exc:
            raise HTTPException(
                status_code=415,
                detail={"reason": "unsupported_attachment", "filename": exc.filename},
            ) from exc
        except AttachmentExtractionError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "reason": "attachment_extraction_failed",
                    "filename": exc.filename,
                    "message": exc.message,
                },
            ) from exc
        if text:
            extracted.append((upload.filename, text))

    enriched = enrich_transcript(transcript=transcript, attachments=extracted)
    log.info(
        "session_estimate_received",
        session_id=session_id,
        transcript_chars=len(transcript),
        enriched_transcript_chars=len(enriched),
        attachment_count=len(extracted),
    )

    try:
        response = service.estimate_conversational(
            session=session,
            transcript=enriched,
            project_type=project_type,
            detail_level=detail_level,
            output_format=output_format,
        )
    except InputGuardrailViolation as exc:
        log.info(
            "session_estimate_blocked_by_input_guardrail",
            reason=exc.reason,
            message=exc.message,
        )
        raise HTTPException(
            status_code=400, detail={"reason": exc.reason, "message": exc.message}
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        log.error(
            "session_estimate_endpoint_error",
            error=str(exc)[:400],
            error_type=type(exc).__name__,
        )
        raise HTTPException(status_code=502, detail="Upstream LLM call failed") from exc

    # Flush the mutated history + metadata back to Postgres.
    store.save(session)

    # Mirror the turn into the estimations grid (one row per session).
    try:
        _mirror_turn_to_grid(
            db,
            session=session,
            transcript=transcript,
            project_type=project_type,
            detail_level=detail_level,
            output_format=output_format,
            response=response,
            model=service.llm_wrapper.primary_model,
        )
    except Exception as exc:  # noqa: BLE001 — grid mirror is best-effort
        db.rollback()
        log.warning(
            "session_estimate_grid_mirror_failed",
            session_id=session_id,
            error_type=type(exc).__name__,
            error=str(exc)[:200],
        )

    return response
