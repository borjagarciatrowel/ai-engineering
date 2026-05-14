from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.schemas.estimation import EstimationRequest

PROMPTS_ROOT = Path(__file__).parent


@lru_cache
def _get_env(version: str) -> Environment:
    return Environment(
        loader=FileSystemLoader(PROMPTS_ROOT / "estimation" / version),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,
        keep_trailing_newline=True,
    )


def render_estimation_prompt(
    request: EstimationRequest, version: str = "v1"
) -> tuple[str, str]:
    """Render system and user prompts for the given request and prompt version.

    Returns a (system, user) tuple ready to feed the LLM wrapper.
    """
    env = _get_env(version)
    ctx = {
        "description": request.description,
        "project_type": request.project_type.value,
        "detail_level": request.detail_level.value,
        "output_format": request.output_format.value,
    }
    system = env.get_template("system.j2").render(**ctx)
    user = env.get_template("user.j2").render(**ctx)
    return system, user
