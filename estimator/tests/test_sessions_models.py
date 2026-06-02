"""Unit tests for ConversationHistory, ProjectMetadata and the DB session store.

The sliding-window / metadata-merge logic is storage-agnostic Pydantic. The
store tests use an in-memory sqlite ``DbSessionStore`` to verify the persistence
round-trip (the project deviation from the brief's in-memory dict).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db_models  # noqa: F401 — register ORM models on Base.metadata
from app.db import Base
from app.sessions.models import ConversationHistory, ProjectMetadata, Session
from app.sessions.store import DbSessionStore, SessionNotFoundError


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    try:
        yield SessionLocal
    finally:
        Base.metadata.drop_all(engine)


# ---- Pydantic model logic (storage-agnostic) ----


def test_history_append_does_not_auto_trim() -> None:
    """As of Session 5 live, append is a pure data operation. Compression is
    the single source of truth for the window — see CompressionPolicy."""
    history = ConversationHistory(max_turns=2)
    history.append(user="t1u", assistant="t1a")
    history.append(user="t2u", assistant="t2a")
    history.append(user="t3u", assistant="t3a")

    messages = history.to_messages()
    assert len(messages) == 6
    assert messages[0] == {"role": "user", "content": "t1u"}
    assert messages[-1] == {"role": "assistant", "content": "t3a"}


def test_history_compression_drops_oldest_non_anchor_pairs() -> None:
    """The sliding-window invariant is now enforced by CompressionPolicy."""
    from unittest.mock import MagicMock

    from app.sessions.compression import apply_compression
    from app.sessions.compression.summarizer import _SummaryEnvelope

    wrapper = MagicMock()
    wrapper.complete_structured_chat.return_value = (
        _SummaryEnvelope(summary="summary text"),
        {"model": "gpt-4o-mini", "provider": "openai", "latency_ms": 1},
    )

    history = ConversationHistory(max_turns=2)
    history.append(user="t1u plain", assistant="t1a")
    history.append(user="t2u plain", assistant="t2a")
    history.append(user="t3u plain", assistant="t3a")

    apply_compression(
        history,
        llm_wrapper=wrapper,
        compression_model="gpt-4o-mini",
        anchor_detection_mode="heuristic",
    )

    # Last 2 pairs verbatim + a summary user message at the front, no anchors.
    messages = history.to_messages()
    assert messages[0]["role"] == "user"
    assert "Earlier conversation summary" in messages[0]["content"]
    assert messages[-1] == {"role": "assistant", "content": "t3a"}
    assert len(history.messages) == 4
    assert history.anchors == []


def test_history_to_messages_excludes_system_prompt() -> None:
    history = ConversationHistory(max_turns=3)
    history.append(user="hi", assistant="hello")
    messages = history.to_messages()
    assert all(m["role"] in {"user", "assistant"} for m in messages)


def test_project_metadata_is_empty_by_default() -> None:
    metadata = ProjectMetadata()
    assert metadata.is_empty()
    assert metadata.mentioned_technologies == []


def test_project_metadata_merge_overwrites_scalars_and_unions_techs() -> None:
    base = ProjectMetadata(
        project_name="Nimbus CRM",
        assumed_team_size=3,
        mentioned_technologies=["React", "Postgres"],
        agreed_scope="Phase 1 only",
    )
    update = ProjectMetadata(
        project_name="Nimbus CRM v2",
        assumed_team_size=None,
        mentioned_technologies=["postgres", "Redis"],
        agreed_scope=None,
    )
    merged = base.merge_with(update)

    assert merged.project_name == "Nimbus CRM v2"  # overwritten
    assert merged.assumed_team_size == 3  # preserved (update was None)
    assert merged.agreed_scope == "Phase 1 only"  # preserved
    # Case-insensitive union, original order preserved
    assert merged.mentioned_technologies == ["React", "Postgres", "Redis"]


def test_session_round_trip_through_json() -> None:
    """Pydantic serialisation works — it is what the DB store dumps to JSON."""
    session = Session()
    session.history.append(user="hi", assistant="hello")
    session.metadata = ProjectMetadata(project_name="Foo")
    raw = session.model_dump(mode="json")
    restored = Session.model_validate(raw)
    assert restored.metadata.project_name == "Foo"
    assert len(restored.history.messages) == 2


# ---- DB-backed store (persistence deviation) ----


def test_store_create_returns_unique_ids(session_factory) -> None:
    store = DbSessionStore(session_factory())
    s1 = store.create()
    s2 = store.create()
    assert s1.session_id != s2.session_id


def test_store_get_or_404_raises_for_unknown(session_factory) -> None:
    store = DbSessionStore(session_factory())
    with pytest.raises(SessionNotFoundError):
        store.get_or_404("nope")


def test_store_respects_configured_max_turns(session_factory) -> None:
    store = DbSessionStore(session_factory(), max_turns=4)
    session = store.create()
    assert session.history.max_turns == 4


def test_store_persists_and_reloads(session_factory) -> None:
    """Mutate a loaded session, save it, and confirm a fresh read sees it.

    This is the whole point of the DB store: a second connection (or a restart)
    must observe the conversation, unlike a process-memory dict.
    """
    writer = DbSessionStore(session_factory())
    session = writer.create()
    sid = session.session_id

    session.history.append(user="We want a CRM called Nimbus.", assistant="{...}")
    session.metadata = ProjectMetadata(
        project_name="Nimbus", mentioned_technologies=["React"]
    )
    writer.save(session)

    # A brand-new store/session simulates another worker / a restart.
    reader = DbSessionStore(session_factory())
    reloaded = reader.get_or_404(sid)
    assert reloaded.metadata.project_name == "Nimbus"
    assert reloaded.metadata.mentioned_technologies == ["React"]
    assert len(reloaded.history.messages) == 2
    assert reloaded.history.messages[0].content == "We want a CRM called Nimbus."
