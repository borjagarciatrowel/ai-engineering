"""Unit tests for the Redis-backed runtime *retrieval* configuration store
(Session 10 toggles: search mode + reranking).

Mirrors the construction style of ``test_runtime_config.py`` (the model-knob
store): a ``fakeredis`` client + a ``Settings`` built with ``_env_file=None`` so
.env never leaks into the test.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import fakeredis
import pytest
import redis as redis_lib

from app.config import Settings
from app.foundation.llm.runtime_config import (
    RERANK_KEY,
    RETRIEVAL_KEYS,
    SEARCH_MODE_KEY,
    RuntimeConfigUnavailable,
    RuntimeRetrievalConfig,
)


def make_settings(**overrides) -> Settings:
    return Settings(OPENAI_API_KEY="sk-test", _env_file=None, **overrides)


@pytest.fixture
def store() -> RuntimeRetrievalConfig:
    return RuntimeRetrievalConfig(fakeredis.FakeRedis(decode_responses=True), make_settings())


def test_effective_falls_back_to_settings_when_no_override(store) -> None:
    """With no override set, both toggles must read straight from Settings."""
    assert store.effective_search_mode() == "vector"  # Settings.RETRIEVAL_SEARCH_MODE default
    assert store.effective_rerank() is False  # Settings.RERANKER_ENABLED default


def test_effective_reflects_non_default_settings() -> None:
    """The fallback follows whatever the .env-configured Settings say."""
    store = RuntimeRetrievalConfig(
        fakeredis.FakeRedis(decode_responses=True),
        make_settings(RETRIEVAL_SEARCH_MODE="hybrid", RERANKER_ENABLED=True),
    )
    assert store.effective_search_mode() == "hybrid"
    assert store.effective_rerank() is True


def test_set_search_mode_round_trip(store) -> None:
    store.set_search_mode("hybrid")
    assert store.effective_search_mode() == "hybrid"
    # Clearing the override falls back to the settings default again.
    store.set_search_mode(None)
    assert store.effective_search_mode() == "vector"


def test_set_rerank_round_trip(store) -> None:
    store.set_rerank(True)
    assert store.effective_rerank() is True
    store.set_rerank(False)
    assert store.effective_rerank() is False
    store.set_rerank(None)
    assert store.effective_rerank() is False  # back to Settings default


def test_invalid_search_mode_rejected(store) -> None:
    with pytest.raises(ValueError, match="Invalid search mode"):
        store.set_search_mode("semantic")


def test_snapshot_shape(store) -> None:
    store.set_search_mode("hybrid")
    snapshot = store.snapshot()
    assert set(snapshot) == set(RETRIEVAL_KEYS)
    assert snapshot[SEARCH_MODE_KEY] == {
        "effective": "hybrid",
        "default": "vector",
        "overridden": True,
    }
    assert snapshot[RERANK_KEY]["overridden"] is False


def test_reads_degrade_to_default_when_redis_down() -> None:
    """A read error must never break the pipeline — fall back to Settings."""
    broken = MagicMock()
    broken.hget.side_effect = redis_lib.RedisError("connection refused")
    store = RuntimeRetrievalConfig(broken, make_settings(RETRIEVAL_SEARCH_MODE="hybrid"))
    assert store.effective_search_mode() == "hybrid"
    assert store.effective_rerank() is False


def test_write_failure_reraises_unavailable() -> None:
    """A write error must surface (the API maps it to 503)."""
    broken = MagicMock()
    broken.hset.side_effect = redis_lib.RedisError("connection refused")
    store = RuntimeRetrievalConfig(broken, make_settings())
    with pytest.raises(RuntimeConfigUnavailable):
        store.set_search_mode("hybrid")
