"""Pydantic schemas for the persisted-estimation CRUD API.

These wrap the stateless estimation contract (``app/schemas/estimation.py``)
with persistence concerns: an id, a human title, a lifecycle status, the stored
result and any error details.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.estimation import (
    DetailLevel,
    EstimationResult,
    OutputFormat,
    ProjectType,
)


class EstimationStatus(str, Enum):
    EDITING = "editing"
    RUNNING = "running"
    FINISHED = "finished"
    ERROR = "error"


class EstimationCreate(BaseModel):
    """New estimation; starts in ``editing``. Only the title is mandatory."""

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=80000)
    project_type: ProjectType = ProjectType.WEB_SAAS
    detail_level: DetailLevel = DetailLevel.MEDIUM
    output_format: OutputFormat = OutputFormat.PHASES_TABLE


class EstimationUpdate(BaseModel):
    """Partial update of an editable estimation. All fields optional."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=80000)
    project_type: ProjectType | None = None
    detail_level: DetailLevel | None = None
    output_format: OutputFormat | None = None


class EstimationListItem(BaseModel):
    """Lightweight row for the landing list."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    status: EstimationStatus
    created_at: datetime
    updated_at: datetime


class EstimationRecord(BaseModel):
    """Full record for the detail view."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    status: EstimationStatus
    description: str
    project_type: ProjectType
    detail_level: DetailLevel
    output_format: OutputFormat
    result: EstimationResult | None = None
    prompt_version: str | None = None
    cached: bool | None = None
    model: str | None = None
    provider: str | None = None
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
    finish_reason: str | None = None
    error_reason: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
