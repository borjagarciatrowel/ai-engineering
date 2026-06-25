"""Unit tests for the generation prompt builder (Session 9)."""

from __future__ import annotations

from app.generation.rag.prompt_builder import build_system_prompt, build_user_message
from app.generation.rag.schemas import EstimationQuery


def test_build_system_prompt_returns_non_empty_string():
    prompt = build_system_prompt()
    assert isinstance(prompt, str)
    assert prompt


def test_build_user_message_includes_function():
    message = build_user_message("<sources>X</sources>", EstimationQuery(function="f"))
    assert isinstance(message, str)
    assert "f" in message
