"""Recall-then-rerank retrieval pipeline (Session 10).

The single ``retrieve()`` entrypoint composes the four configurations the exercise
measures, behind two switches the caller resolves (param → settings default):

* ``search_mode="vector"`` — dense k-NN only (the Session 8 baseline).
* ``search_mode="hybrid"`` — dense + lexical (full-text) branches fused with RRF.
* ``rerank=False`` — keep the top ``top_k`` of the recall ordering.
* ``rerank=True``  — recall WIDE (``recall_k``, e.g. 50) then let the cross-encoder
  rescore and keep the top ``rerank_top_n`` (e.g. 5). The recall stage's only job
  is not to lose the relevant document; the reranker's job is to float it up.

``search_mode``/``rerank`` fall back to ``RETRIEVAL_SEARCH_MODE``/``RERANKER_ENABLED``
when ``None`` — so the default behaviour flips via env var, "without touching code"
(exercise step 3). It returns the same ``list[SearchHit]`` as the Session-8
retriever, best-first, so any consumer of a ranked chunk list is unaffected.

Divergences from the reference solution (kept deliberately; see the session-10 doc):
our store exposes the Session-8 ``search`` (plain cosine k-NN), not a Session-9
``search_filtered`` — so the vector branch has no structural pre-filter or distance
threshold (metadata filtering is explicitly out of this exercise's scope). The
contract is ``SearchHit`` (``budget_id`` rides inside ``.metadata``), not the
reference's ``RetrievedChunk``/``RetrievalResult``.
"""

from __future__ import annotations

import asyncio
import time

import structlog

from app.config import get_settings
from app.generation.rag.retrieval.fusion import reciprocal_rank_fusion
from app.generation.rag.schemas import SearchHit

log = structlog.get_logger()

# Distance assigned to a candidate surfaced ONLY by the lexical branch (it never
# entered the vector ranking, so it has no cosine distance). 1.0 = "far" in cosine
# terms; it is a display/sentinel value — fusion and reranking ignore it.
_NO_VECTOR_DISTANCE = 1.0


def _row_to_hit(row, *, distance: float) -> SearchHit:
    """Map a DB row (vector or lexical) onto the Session-8 retrieval contract."""
    return SearchHit(
        chunk_id=row.id,
        document_id=row.document_id,
        chunk_type=row.chunk_type,
        content=row.content,
        distance=distance,
        metadata=row.metadata_,
    )


async def retrieve(
    *,
    query_embedding: list[float],
    query_text: str,
    search_mode: str | None = None,
    rerank: bool | None = None,
    top_k: int = 5,
    recall_k: int = 50,
    rerank_top_n: int = 5,
    rrf_k: int = 60,
    reranker=None,
) -> list[SearchHit]:
    """Run hybrid/vector retrieval with optional cross-encoder reranking.

    ``query_text`` is required for the lexical branch and the reranker even when
    ``search_mode`` is ``"vector"`` (the reranker scores against the raw query).
    ``reranker`` is injectable for tests; when ``None`` and ``rerank`` is True it
    is pulled from the composition root (loads the model lazily on first use).

    Returns the top results best-first (cross-encoder order when reranking, else
    RRF/distance order). An empty list means nothing was retrieved.
    """
    from app.dependencies import get_async_session_factory, get_chunk_store

    if search_mode is None or rerank is None:
        settings = get_settings()
        if search_mode is None:
            search_mode = settings.RETRIEVAL_SEARCH_MODE
        if rerank is None:
            rerank = settings.RERANKER_ENABLED

    session_factory = get_async_session_factory()
    store = get_chunk_store()
    started = time.perf_counter()

    # Recall wide whenever a later stage (fusion or rerank) will re-sort; recall
    # exactly top_k only for the plain vector path, where the order is final.
    wide = rerank or search_mode == "hybrid"
    vector_limit = recall_k if wide else top_k

    async with session_factory() as session:
        vector_rows = await store.search(session, query_vector=query_embedding, k=vector_limit)
        lexical_rows = []
        if search_mode == "hybrid":
            lexical_rows = await store.search_lexical(
                session, query_text=query_text, top_k=recall_k
            )

    # Build the candidate pool once (id → hit); vector distance wins over the
    # lexical sentinel when an id is in both branches.
    candidates: dict[int, SearchHit] = {}
    for row in vector_rows:
        candidates[row.id] = _row_to_hit(row, distance=float(row.distance))
    for row in lexical_rows:
        candidates.setdefault(row.id, _row_to_hit(row, distance=_NO_VECTOR_DISTANCE))

    # Recall ordering: RRF for hybrid, raw distance order for vector.
    if search_mode == "hybrid":
        fused = reciprocal_rank_fusion(
            [[row.id for row in vector_rows], [row.id for row in lexical_rows]],
            k=rrf_k,
        )
        ordered = [candidates[cid] for cid, _score in fused]
    else:
        ordered = [candidates[row.id] for row in vector_rows]

    if rerank and ordered:
        if reranker is None:
            from app.dependencies import get_reranker

            reranker = get_reranker()
        recall_pool = ordered[:recall_k]
        final = await asyncio.to_thread(
            reranker.rerank, query_text, recall_pool, top_n=rerank_top_n
        )
    else:
        final = ordered[:top_k]

    log.info(
        "rag_retrieve_done",
        search_mode=search_mode,
        rerank=rerank,
        vector_hits=len(vector_rows),
        lexical_hits=len(lexical_rows),
        results=len(final),
        search_time_ms=int((time.perf_counter() - started) * 1000),
    )
    return final
