from enum import Enum

from pydantic import BaseModel, Field


class ProjectType(str, Enum):
    MOBILE_APP = "mobile_app"
    WEB_SAAS = "web_saas"
    INTERNAL_TOOL = "internal_tool"
    DATA_PIPELINE = "data_pipeline"


class DetailLevel(str, Enum):
    SUMMARY = "summary"
    MEDIUM = "medium"
    DETAILED = "detailed"


class OutputFormat(str, Enum):
    PHASES_TABLE = "phases_table"
    LINE_ITEMS = "line_items"
    NARRATIVE = "narrative"


class EstimationRequest(BaseModel):
    """Typed estimation request produced by the Angular form."""

    description: str = Field(min_length=20, max_length=2000)
    project_type: ProjectType
    detail_level: DetailLevel
    output_format: OutputFormat


class TokenUsage(BaseModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int


class EstimationResponse(BaseModel):
    """Plain response with rendered text and the prompt version used."""

    text: str
    prompt_version: str
    model: str | None = None
    provider: str | None = None
    usage: TokenUsage | None = None
