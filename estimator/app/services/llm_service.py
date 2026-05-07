import json
from collections.abc import Generator

import structlog

from app.config import get_settings
from app.context.examples import ESTIMATION_EXAMPLES, format_examples_for_prompt

log = structlog.get_logger()

MAX_TOKENS = 4000


class LLMServiceError(Exception):
    """Raised when the LLM provider call fails."""


def build_system_prompt() -> str:
    """Construct the system prompt with role definition and reference examples."""
    examples_text = format_examples_for_prompt(ESTIMATION_EXAMPLES)
    return (
        "You are a senior software consultant with 15+ years of experience in project "
        "estimation. Your task is to produce a detailed software project estimation based "
        "on a meeting transcription provided by the user.\n\n"
        "Below are reference estimations from previous projects. Use them as a guide for "
        "structure, level of detail, and realistic pricing. Adapt the content to match the "
        "specific project described in the transcription.\n\n"
        "Your output MUST follow this exact format:\n"
        "- Project title as an H2 heading\n"
        "- A task breakdown table with columns: Task, Hours, Cost (EUR)\n"
        "- Total hours\n"
        "- Total cost in EUR\n"
        "- Recommended team composition\n"
        "- Estimated duration in weeks\n\n"
        "Use a developer rate of approximately 62.50 EUR/hour (500 EUR/day) and a designer "
        "rate of approximately 50 EUR/hour (400 EUR/day). Provide realistic, well-justified "
        "numbers.\n\n"
        f"{examples_text}"
    )


def generate_estimation(transcription: str) -> dict:
    """Generate a software estimation from a meeting transcription using the configured LLM."""
    settings = get_settings()
    system_prompt = build_system_prompt()

    log.info("generating_estimation", provider=settings.LLM_PROVIDER, model=settings.LLM_MODEL)

    try:
        if settings.LLM_PROVIDER == "openai":
            return _call_openai(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": transcription},
                ],
            )
        else:
            return _call_anthropic(
                system=system_prompt,
                user_message=transcription,
            )
    except LLMServiceError:
        raise
    except Exception as exc:
        log.error("llm_call_failed", error=str(exc), provider=settings.LLM_PROVIDER)
        raise LLMServiceError(f"LLM call failed: {exc}") from exc


def _call_openai(messages: list[dict]) -> dict:
    """Send a chat completion request to the OpenAI API."""
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
    """Send a message request to the Anthropic API."""
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


def stream_estimation(transcription: str) -> Generator[bytes, None, None]:
    """Stream a software estimation as NDJSON bytes.

    Each yielded line is either:
    - {"t": "<text chunk>"}  — partial text token
    - {"done": true, "model": "...", "provider": "...", "usage": {...}}  — final metadata
    """
    settings = get_settings()
    system_prompt = build_system_prompt()

    log.info("stream_estimation_start", provider=settings.LLM_PROVIDER, model=settings.LLM_MODEL)

    try:
        if settings.LLM_PROVIDER == "openai":
            yield from _stream_openai(system_prompt, transcription)
        else:
            yield from _stream_anthropic(system_prompt, transcription)
    except Exception as exc:
        log.error("stream_estimation_failed", error=str(exc), provider=settings.LLM_PROVIDER)
        raise LLMServiceError(f"LLM streaming failed: {exc}") from exc


def _stream_openai(system_prompt: str, transcription: str) -> Generator[bytes, None, None]:
    from openai import OpenAI

    settings = get_settings()
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    model_used = settings.LLM_MODEL
    usage_data: dict = {}

    stream = client.chat.completions.create(
        model=settings.LLM_MODEL,
        max_tokens=MAX_TOKENS,
        stream=True,
        stream_options={"include_usage": True},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": transcription},
        ],
    )

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

    usage_data.setdefault("input_tokens", 0)
    usage_data.setdefault("output_tokens", 0)
    usage_data.setdefault("total_tokens", 0)

    yield json.dumps({
        "done": True,
        "model": model_used,
        "provider": "openai",
        "usage": usage_data,
    }).encode() + b"\n"


def _stream_anthropic(system_prompt: str, transcription: str) -> Generator[bytes, None, None]:
    from anthropic import Anthropic

    settings = get_settings()
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    with client.messages.stream(
        model=settings.LLM_MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": transcription}],
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
