import pytest

from app.prompts.loader import render_estimation_prompt
from app.schemas.estimation import (
    DetailLevel,
    EstimationRequest,
    OutputFormat,
    ProjectType,
)


BASE_DESCRIPTION = (
    "We want an internal app to track maintenance tickets for our 12 office buildings, "
    "with role-based access and Slack notifications."
)


def _make_request(
    *,
    output_format: OutputFormat = OutputFormat.PHASES_TABLE,
    detail_level: DetailLevel = DetailLevel.MEDIUM,
    description: str = BASE_DESCRIPTION,
    project_type: ProjectType = ProjectType.INTERNAL_TOOL,
) -> EstimationRequest:
    return EstimationRequest(
        description=description,
        project_type=project_type,
        detail_level=detail_level,
        output_format=output_format,
    )


def test_user_template_includes_description_verbatim():
    request = _make_request()
    _system, user = render_estimation_prompt(request)

    assert "<project_description>" in user
    assert BASE_DESCRIPTION in user
    # Ensure the description sits inside the project_description block
    block = user.split("<project_description>")[1].split("</project_description>")[0]
    assert BASE_DESCRIPTION in block


def test_phases_table_keyword_appears_only_when_selected():
    phases_system, _ = render_estimation_prompt(_make_request(output_format=OutputFormat.PHASES_TABLE))
    narrative_system, _ = render_estimation_prompt(_make_request(output_format=OutputFormat.NARRATIVE))

    assert "phases_table" in phases_system
    assert "confidence_pct" in phases_system

    assert "phases_table" not in narrative_system
    assert "confidence_pct" not in narrative_system


def test_detailed_level_adds_assumptions_instruction():
    detailed_system, _ = render_estimation_prompt(_make_request(detail_level=DetailLevel.DETAILED))
    summary_system, _ = render_estimation_prompt(_make_request(detail_level=DetailLevel.SUMMARY))

    assert "list assumptions per phase" in detailed_system.lower()
    assert "list assumptions per phase" not in summary_system.lower()


def test_examples_are_embedded_via_include():
    system, _ = render_estimation_prompt(_make_request())
    # Few-shot examples block must appear in the rendered system prompt.
    assert "EXAMPLE 1" in system
    assert "EXAMPLE 2" in system
    assert "EXAMPLE 3" in system


def test_unknown_version_raises():
    with pytest.raises(Exception):
        render_estimation_prompt(_make_request(), version="v999")
