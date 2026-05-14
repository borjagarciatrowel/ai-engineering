import json
from collections.abc import Generator

import structlog

from app.config import get_settings

log = structlog.get_logger()

MAX_TOKENS = 4000


class LLMServiceError(Exception):
    """Raised when the LLM provider call fails."""


def generate_estimation(system_prompt: str, user_message: str) -> dict:
    """Generate a software estimation given pre-rendered system and user prompts."""
    settings = get_settings()

    log.info("generating_estimation", provider=settings.LLM_PROVIDER, model=settings.LLM_MODEL)

    try:
        if settings.LLM_PROVIDER == "openai":
            return _call_openai(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
            )
        else:
            return _call_anthropic(system=system_prompt, user_message=user_message)
    except LLMServiceError:
        raise
    except Exception as exc:
        log.error("llm_call_failed", error=str(exc), provider=settings.LLM_PROVIDER)
        raise LLMServiceError(f"LLM call failed: {exc}") from exc


def _call_openai(messages: list[dict]) -> dict:
    from openai import OpenAI

    settings = get_settings()
    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    response = client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=messages,
        max_tokens=MAX_TOKENS,
    )

    usage = response.usage
    log.info(
        "llm_response_received",
        provider="openai",
        input_tokens=usage.prompt_tokens,
        output_tokens=usage.completion_tokens,
    )

    return {
        "estimation": response.choices[0].message.content,
        "model": response.model,
        "provider": "openai",
        "usage": {
            "input_tokens": usage.prompt_tokens,
            "output_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        },
    }


def _call_anthropic(system: str, user_message: str) -> dict:
    from anthropic import Anthropic

    settings = get_settings()
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    response = client.messages.create(
        model=settings.LLM_MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )

    log.info(
        "llm_response_received",
        provider="anthropic",
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )

    return {
        "estimation": response.content[0].text,
        "model": response.model,
        "provider": "anthropic",
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
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

    if settings.LLM_PROVIDER == "openai":
        yield from _stream_openai(system_prompt, user_message)
    else:
        yield from _stream_anthropic(system_prompt, user_message)


def _stream_openai(system_prompt: str, user_message: str) -> Generator[bytes, None, None]:
    from openai import OpenAI

    settings = get_settings()
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    model_used = settings.LLM_MODEL
    usage_data: dict = {}
    _error_occurred = False
    try:
        with client.chat.completions.create(
            model=settings.LLM_MODEL,
            max_tokens=MAX_TOKENS,
            stream=True,
            stream_options={"include_usage": True},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        ) as stream:
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield json.dumps({"t": chunk.choices[0].delta.content}).encode() + b"\n"
                if chunk.model:
                    model_used = chunk.model
                if chunk.usage:
                    usage_data = {
                        "input_tokens": chunk.usage.prompt_tokens,
                        "output_tokens": chunk.usage.completion_tokens,
                        "total_tokens": chunk.usage.total_tokens,
                    }
    except LLMServiceError:
        _error_occurred = True
        raise
    except Exception as exc:
        _error_occurred = True
        log.error("stream_openai_failed", error=str(exc))
        raise LLMServiceError(f"OpenAI streaming failed: {exc}") from exc
    finally:
        if not _error_occurred:
            usage_data.setdefault("input_tokens", 0)
            usage_data.setdefault("output_tokens", 0)
            usage_data.setdefault("total_tokens", 0)
            yield json.dumps({
                "done": True,
                "model": model_used,
                "provider": "openai",
                "usage": usage_data,
            }).encode() + b"\n"


def _stream_anthropic(system_prompt: str, user_message: str) -> Generator[bytes, None, None]:
    from anthropic import Anthropic

    settings = get_settings()
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    try:
        with client.messages.stream(
            model=settings.LLM_MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            for text in stream.text_stream:
                yield json.dumps({"t": text}).encode() + b"\n"

            msg = stream.get_final_message()
            yield json.dumps({
                "done": True,
                "model": msg.model,
                "provider": "anthropic",
                "usage": {
                    "input_tokens": msg.usage.input_tokens,
                    "output_tokens": msg.usage.output_tokens,
                    "total_tokens": msg.usage.input_tokens + msg.usage.output_tokens,
                },
            }).encode() + b"\n"
    except LLMServiceError:
        raise
    except Exception as exc:
        log.error("stream_anthropic_failed", error=str(exc))
        raise LLMServiceError(f"Anthropic streaming failed: {exc}") from exc
