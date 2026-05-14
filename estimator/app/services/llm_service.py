import json
from collections.abc import Generator

import litellm
import structlog

from app.config import get_settings

log = structlog.get_logger()

MAX_TOKENS = 4000


class LLMServiceError(Exception):
    """Raised when the LLM provider call fails."""


def _api_key_for_provider(provider: str) -> str | None:
    settings = get_settings()
    if provider == "openai":
        return settings.OPENAI_API_KEY
    if provider == "anthropic":
        return settings.ANTHROPIC_API_KEY
    return None


def _completion_kwargs(system_prompt: str, user_message: str) -> dict:
    settings = get_settings()
    return {
        "model": settings.LLM_MODEL,
        "custom_llm_provider": settings.LLM_PROVIDER,
        "api_key": _api_key_for_provider(settings.LLM_PROVIDER),
        "max_tokens": MAX_TOKENS,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    }


def estimation(system_prompt: str, user_message: str) -> dict:
    """Generate a software estimation given pre-rendered system and user prompts."""
    settings = get_settings()

    log.info("generating_estimation", provider=settings.LLM_PROVIDER, model=settings.LLM_MODEL)

    try:
        response = litellm.completion(**_completion_kwargs(system_prompt, user_message))
    except LLMServiceError:
        raise
    except Exception as exc:
        log.error("llm_call_failed", error=str(exc), provider=settings.LLM_PROVIDER)
        raise LLMServiceError(f"LLM call failed: {exc}") from exc

    usage = response.usage
    log.info(
        "llm_response_received",
        provider=settings.LLM_PROVIDER,
        input_tokens=usage.prompt_tokens,
        output_tokens=usage.completion_tokens,
    )

    return {
        "estimation": response.choices[0].message.content,
        "model": response.model,
        "provider": settings.LLM_PROVIDER,
        "usage": {
            "input_tokens": usage.prompt_tokens,
            "output_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        },
    }


def stream_estimation(system_prompt: str, user_message: str) -> Generator[bytes, None, None]:
    """Stream a software estimation as NDJSON bytes.

    Each yielded line is either:
    - {"t": "<text chunk>"}  — partial text token
    - {"done": true, "model": "...", "provider": "...", "usage": {...}}  — final metadata
    """
    settings = get_settings()

    log.info("stream_estimation_start", provider=settings.LLM_PROVIDER, model=settings.LLM_MODEL)

    model_used = settings.LLM_MODEL
    usage_data: dict = {}
    error_occurred = False
    try:
        stream = litellm.completion(
            **_completion_kwargs(system_prompt, user_message),
            stream=True,
            stream_options={"include_usage": True},
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield json.dumps({"t": chunk.choices[0].delta.content}).encode() + b"\n"
            chunk_model = getattr(chunk, "model", None)
            if chunk_model:
                model_used = chunk_model
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage:
                usage_data = {
                    "input_tokens": chunk_usage.prompt_tokens,
                    "output_tokens": chunk_usage.completion_tokens,
                    "total_tokens": chunk_usage.total_tokens,
                }
    except LLMServiceError:
        error_occurred = True
        raise
    except Exception as exc:
        error_occurred = True
        log.error("stream_failed", error=str(exc), provider=settings.LLM_PROVIDER)
        raise LLMServiceError(f"LLM streaming failed: {exc}") from exc
    finally:
        if not error_occurred:
            usage_data.setdefault("input_tokens", 0)
            usage_data.setdefault("output_tokens", 0)
            usage_data.setdefault("total_tokens", 0)
            yield json.dumps({
                "done": True,
                "model": model_used,
                "provider": settings.LLM_PROVIDER,
                "usage": usage_data,
            }).encode() + b"\n"
