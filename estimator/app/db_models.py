"""ORM model for a persisted estimation request and its lifecycle.

Status lifecycle:
    editing  → user is still composing the request (default on create)
    running  → the pipeline is executing (set before the LLM call)
    finished → a validated EstimationResult was stored
    error    → guardrail rejection or upstream/LLM failure (reason + message stored)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Estimation(Base):
    __tablename__ = "estimations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="editing", index=True)

    # Set when this row mirrors a conversational session (one row per session,
    # updated each turn) so conversational estimations show in the grid too.
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    # Request payload
    description: Mapped[str] = mapped_column(Text, default="")
    project_type: Mapped[str] = mapped_column(String(40))
    detail_level: Mapped[str] = mapped_column(String(20))
    output_format: Mapped[str] = mapped_column(String(20))

    # Result + model metadata (populated on a successful run)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cached: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # LLM call telemetry (monitoring / cost tracking)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # Error info (populated on a failed run)
    error_reason: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ChatSession(Base):
    """A persisted conversational estimation session (Session 5).

    The Session-5 brief keeps conversational memory in a process-memory dict.
    We persist it instead: ``history`` and ``project_metadata`` are the JSON
    dumps of the Pydantic ``ConversationHistory`` / ``ProjectMetadata`` models,
    so a restart (or a second worker) doesn't drop the conversation.

    Note: the column is ``project_metadata``, not ``metadata`` — ``metadata`` is
    reserved on SQLAlchemy's declarative ``Base``.
    """

    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    max_turns: Mapped[int] = mapped_column(Integer, default=6)
    history: Mapped[dict] = mapped_column(JSON, default=dict)
    project_metadata: Mapped[dict] = mapped_column(JSON, default=dict)

    # Cached audience-tier resolution (Session 5 live). Recomputed each turn by
    # ``tier_resolver.resolve_tier``; persisted so GET /sessions/{id} can show
    # the tier side panel without re-running the resolver after a cold load.
    last_resolved_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_tier_rule: Mapped[str | None] = mapped_column(String(40), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
