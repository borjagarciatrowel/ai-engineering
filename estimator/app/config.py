from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Session 2 fields (kept for backwards compatibility with the live demos) ---
    OPENAI_API_KEY: str | None = None
    ANTHROPIC_API_KEY: str | None = None
    LLM_PROVIDER: Literal["openai", "anthropic"] = "anthropic"
    LLM_MODEL: str = "claude-haiku-4-5"
    APP_ENV: Literal["development", "staging", "production"] = "development"
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "DEBUG"

    # --- Session 3 fields (LiteLLM wrapper, Redis cache, Streamlit transport) ---
    PRIMARY_MODEL: str = "gpt-4o-mini"
    FALLBACK_MODEL: str = "claude-haiku-4-5-20251001"
    # Session 7 live: catalog of models selectable at runtime via
    # PUT /api/v1/config/models (kept aligned with MODEL_COSTS in
    # app/foundation/llm/wrapper.py). The endpoint filters this list by the API
    # keys actually configured.
    AVAILABLE_MODELS: list[str] = [
        "gpt-4o-mini",
        "gpt-4o",
        "claude-haiku-4-5-20251001",
        "claude-sonnet-4-5",
    ]
    LLM_TIMEOUT: int = 30
    LLM_RETRIES: int = 2

    REDIS_URL: str = "redis://localhost:6379"
    CACHE_TTL: int = 86400

    # --- Persistence (Postgres) ---
    DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@localhost:5432/estimator"

    # --- Session 4 fields (semantic cache) ---
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    SEMANTIC_CACHE_THRESHOLD: float = 0.85
    SEMANTIC_CACHE_TTL: int = 86400
    # When True, the semantic cache LOGS potential hits but does NOT serve them.
    # Used to gather metrics before flipping the cache on in production.
    SEMANTIC_CACHE_LOG_ONLY: bool = False

    ESTIMATOR_API_BASE_URL: str = "http://localhost:8000"

    # --- Session 5 fields (conversational memory + attachments) ---
    # MAX_CONVERSATION_TURNS counts user+assistant pairs. The system prompt is
    # always regenerated on top of the window from the current ProjectMetadata.
    MAX_CONVERSATION_TURNS: int = 6
    # Hard cap per extracted attachment (in characters) to protect the context
    # window. Real chunking enters in module 3.
    MAX_ATTACHMENT_CHARS: int = 60_000
    # The metadata extractor runs once per turn; a small/cheap model is enough.
    METADATA_EXTRACTOR_MODEL: str = "gpt-4o-mini"

    # --- Session 5 live: compression + tier + ACB ---
    # Anchor detector: "heuristic" (regex over key phrases) or "llm" (binary
    # classifier via Instructor). Heuristic is the default for cost.
    ANCHOR_DETECTION_MODE: Literal["heuristic", "llm"] = "heuristic"
    # Cheap model used by the cumulative summarizer (history compression).
    COMPRESSION_MODEL: str = "gpt-4o-mini"
    # Conversational prompt version used by ``estimate_conversational`` and the
    # ACB actor. v2 = pre-live-session baseline. v3 = adds the <audience> block
    # driven by tier and an optional <critic_feedback> block consumed by the Boss.
    CONVERSATIONAL_PROMPT_VERSION: str = "v3"
    # Critic model (read-only auditor; cheap is fine).
    CRITIC_MODEL: str = "gpt-4o-mini"
    # Max iterations the Boss can drive (each iteration = 1 actor + 1 critic call).
    # Three is the practical floor: one initial draft + two directed retries.
    # With only two iterations the actor often cannot address all flagged issues
    # in the single available retry, and the loop falls back without converging.
    BOSS_MAX_ITERATIONS: int = 3

    # --- Session 6 (CAG stress test) ---
    # The phases-sum business rule (per-phase costs must equal total_cost_eur)
    # is enforced by default. The stress runner sets ENFORCE_PHASES_SUM=false
    # because gpt-4o-mini cannot reliably make the two match; the repeated
    # Instructor re-prompts otherwise turn into 502s and abort sessions on turn
    # 1, which destroys the measurement (under load we care about latency, cost
    # and memory drift, not the euro-accuracy of the estimate). Keep it True in
    # production — it is a real business-rule guardrail.
    ENFORCE_PHASES_SUM: bool = True

    # --- Session 6 live (data-driven AI: ingestion + PII) ---
    # We reuse the single Postgres declared above (DATABASE_URL). In Session 6
    # it backs two new tables (pseudonym_mappings, ingestion_jobs) created by
    # Alembic. The compose image is pgvector/pgvector:pg16 so Session 7 can
    # enable the vector extension via a follow-up migration — no extension is
    # activated yet here.
    # Where the YAML catalog lives, resolved relative to the working directory.
    CATALOG_PATH: Path = Path("data/catalog/catalog.yaml")
    # Root that ``CatalogSource.location`` entries are resolved against.
    INGESTION_DATA_ROOT: Path = Path("data/seed")
    # spaCy model loaded by the Presidio AnalyzerEngine. Must be the Spanish one
    # or Presidio silently misses Hispanic names. ``es_core_news_md`` recommended.
    PRESIDIO_SPACY_MODEL: str = "es_core_news_md"
    # Faker locale used to generate consistent pseudonyms per entity_type.
    PSEUDONYM_FAKER_LOCALE: str = "es_ES"
    # HMAC salt for the pseudonym mapping hash. Rotating it invalidates all prior
    # mappings (the GDPR Art. 17 lever). CHANGE IN PROD — kept in env, not code.
    PSEUDONYM_HASH_SALT: str = "change-me-in-prod"

    # --- Session 7 live fields (chunking strategies that call external APIs) ---
    # LLM that decomposes a component into atomic propositions (one call per
    # component). A small/cheap model is enough.
    PROPOSITIONAL_CHUNKER_MODEL: str = "gpt-4o-mini"
    # Claude model used by Contextual Retrieval to situate each chunk inside its
    # parent budget. Prompt caching makes the (large) parent document cheap to
    # reuse across the chunks of the same budget.
    CONTEXTUAL_CHUNKER_MODEL: str = "claude-sonnet-4-5"

    @model_validator(mode="after")
    def validate_at_least_one_api_key(self) -> "Settings":
        """LiteLLM may try either provider via fallback, so we require at least one key."""
        if not self.OPENAI_API_KEY and not self.ANTHROPIC_API_KEY:
            raise ValueError(
                "At least one of OPENAI_API_KEY or ANTHROPIC_API_KEY must be set"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings (singleton)."""
    return Settings()
