"""Session 5 — conversational memory (persisted to Postgres).

Two structures, separated on purpose:

- ``ConversationHistory`` is the rolling array of ``messages`` sent to the LLM
  every turn. It implements a sliding window: when ``MAX_TURNS`` is exceeded,
  the oldest pairs are dropped.
- ``ProjectMetadata`` captures the *facts* of the project under discussion
  (name, team, technologies, agreed scope). It lives outside the history and
  is injected into the system prompt every turn — that's how the model
  remembers context that would otherwise be evicted by the sliding window.

The ``Session`` owns both, plus a ``session_id`` and a creation timestamp.
``DbSessionStore`` persists each session as a ``chat_sessions`` row, so memory
survives a restart and is shared across workers — the project deviation from
the brief's in-memory dict.
"""

from app.sessions.models import (
    ConversationHistory,
    Message,
    ProjectMetadata,
    Session,
)
from app.sessions.store import DbSessionStore, SessionNotFoundError

__all__ = [
    "ConversationHistory",
    "Message",
    "ProjectMetadata",
    "Session",
    "DbSessionStore",
    "SessionNotFoundError",
]
