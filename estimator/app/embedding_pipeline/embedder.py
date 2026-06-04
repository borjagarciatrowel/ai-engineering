"""OpenAI embedder for the embedding pipeline (Session 7).

Wraps the OpenAI Embeddings API with three production concerns the bare SDK
call leaves to the caller:

* **Batching** — ``embed_many`` sends up to ``BATCH_SIZE`` chunks per request
  (the ``embeddings.create`` endpoint accepts a list), instead of one serialised
  call per chunk.
* **Retries** — ``RateLimitError`` is retried with simple exponential backoff
  (1s, 2s, 4s). Any other error propagates up.
* **Observability** — every batch is logged with structlog (chunk count, token
  count, latency), following the logging convention from Session 3.
"""
from __future__ import annotations

import time

import structlog
from openai import OpenAI, RateLimitError

from app.embedding_pipeline.schemas import Chunk, EmbeddedChunk

log = structlog.get_logger()

# Default embedding model and its native dimensionality (1536). We do NOT force
# a smaller dimension here — the Matryoshka discussion belongs to the live
# session.
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536

# Chunks per API call. The endpoint accepts a list; 100 keeps requests fat
# without hitting per-request input limits.
BATCH_SIZE = 100

# Retry policy for RateLimitError: 3 retries with these waits (seconds).
RETRY_BACKOFF_SECONDS = (1, 2, 4)

# Price of text-embedding-3-small input tokens, in USD per million tokens.
# This is a moving target — keep it as a clearly labelled module constant.
PRICE_PER_MILLION_TOKENS_USD = 0.02


def estimated_cost_usd(total_tokens: int) -> float:
    """USD cost estimate for embedding ``total_tokens`` input tokens."""
    return total_tokens / 1_000_000 * PRICE_PER_MILLION_TOKENS_USD


class OpenAIEmbedder:
    """Thin, retrying, batching wrapper over the OpenAI Embeddings API."""

    def __init__(
        self,
        client: OpenAI,
        model: str = EMBEDDING_MODEL,
        batch_size: int = BATCH_SIZE,
    ) -> None:
        self._client = client
        self._model = model
        self._batch_size = batch_size

    def embed_one(self, text: str) -> list[float]:
        """Embed a single string and return its vector."""
        vectors = self._create_with_retry([text])
        return vectors[0]

    def embed_many(self, chunks: list[Chunk]) -> list[EmbeddedChunk]:
        """Embed a list of chunks in batches, preserving input order."""
        embedded: list[EmbeddedChunk] = []
        for start in range(0, len(chunks), self._batch_size):
            batch = chunks[start : start + self._batch_size]
            batch_tokens = sum(c.token_count for c in batch)

            started = time.perf_counter()
            vectors = self._create_with_retry([c.text for c in batch])
            latency_ms = round((time.perf_counter() - started) * 1000, 1)

            log.info(
                "embeddings_batch_processed",
                model=self._model,
                chunks=len(batch),
                tokens=batch_tokens,
                latency_ms=latency_ms,
            )

            for chunk, vector in zip(batch, vectors):
                embedded.append(
                    EmbeddedChunk(**chunk.model_dump(), embedding=vector)
                )
        return embedded

    # ----------------------------------------------------------------------- #
    # Internals
    # ----------------------------------------------------------------------- #
    def _create_with_retry(self, inputs: list[str]) -> list[list[float]]:
        """Call ``embeddings.create`` retrying RateLimitError with backoff."""
        last_error: RateLimitError | None = None
        # 1 initial attempt + len(RETRY_BACKOFF_SECONDS) retries.
        for attempt, wait in enumerate((0, *RETRY_BACKOFF_SECONDS)):
            if wait:
                time.sleep(wait)
            try:
                response = self._client.embeddings.create(
                    model=self._model,
                    input=inputs,
                )
                # The API may return data out of order; sort by index to be safe.
                ordered = sorted(response.data, key=lambda d: d.index)
                return [d.embedding for d in ordered]
            except RateLimitError as exc:
                last_error = exc
                log.warning(
                    "embeddings_rate_limited",
                    attempt=attempt + 1,
                    next_wait_s=(
                        RETRY_BACKOFF_SECONDS[attempt]
                        if attempt < len(RETRY_BACKOFF_SECONDS)
                        else None
                    ),
                )
        # Exhausted retries — propagate the last rate-limit error upward.
        assert last_error is not None
        raise last_error
