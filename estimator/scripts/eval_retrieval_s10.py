#!/usr/bin/env python3
"""Measure retrieval quality across the four Session 10 configurations.

Runs the golden set (``evals/golden_retrieval.json``) through the same
``retrieve()`` pipeline the app uses, for each of:

    A  Vector  / no rerank   (the Session 8 baseline)
    B  Hybrid  / no rerank
    C  Vector  / rerank
    D  Hybrid  / rerank

and reports precision@5 (mean over the queries) and query latency (mean over
measured runs) per configuration, plus a per-query precision breakdown.

Method notes:
* Queries are embedded ONCE upfront; embedding latency is an OpenAI round-trip
  shared by every config, so it is excluded from the timings (we measure the
  retrieval/rerank cost the techniques actually add).
* A retrieved chunk is relevant iff its parent ``budget_id`` (inside the chunk
  metadata) is in the query's annotated ``relevant_budget_ids``.
  precision@5 = relevant_in_top5 / 5.

Usage (host, Postgres up + corpus ingested + OPENAI_API_KEY in .env)::

    uv run python scripts/eval_retrieval_s10.py

Reranking configs download the cross-encoder weights on first use; verify first
with ``uv run python -m app.generation.rag.retrieval.verify_reranker``.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

# Make ``app`` importable regardless of the working directory: this file lives at
# estimator/scripts/eval_retrieval_s10.py, so the project root is one level up.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings  # noqa: E402
from app.dependencies import get_embedder, get_reranker  # noqa: E402
from app.generation.rag.retrieval.pipeline import retrieve  # noqa: E402

GOLDEN_PATH = PROJECT_ROOT / "evals" / "golden_retrieval.json"

# (id, search label, rerank label, search_mode, rerank)
CONFIGS = [
    ("A", "Vector", "No", "vector", False),
    ("B", "Hybrid", "No", "hybrid", False),
    ("C", "Vector", "Yes", "vector", True),
    ("D", "Hybrid", "Yes", "hybrid", True),
]

# Latency sampling per (query, config): one discarded warm-up + N measured runs.
MEASURED_RUNS = 3


class _Stopwatch:
    """Context manager measuring wall-clock milliseconds for the block."""

    def __enter__(self) -> "_Stopwatch":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_exc) -> bool:
        self.elapsed_ms = (time.perf_counter() - self._start) * 1000
        return False


def precision_at_k(hits, relevant_ids: set[str], k: int) -> float:
    """Fraction of the top-k results whose parent budget is genuinely relevant."""
    top = hits[:k]
    matches = sum(1 for hit in top if hit.metadata.get("budget_id") in relevant_ids)
    return matches / k


async def _run_once(query_embedding, query_text, search_mode, rerank, settings, k):
    return await retrieve(
        query_embedding=query_embedding,
        query_text=query_text,
        search_mode=search_mode,
        rerank=rerank,
        top_k=k,
        recall_k=settings.RETRIEVAL_RECALL_TOP_K,
        rerank_top_n=k,
        rrf_k=settings.RRF_K,
    )


async def main() -> int:
    settings = get_settings()
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    queries = golden["queries"]
    k = int(golden.get("k", 5))

    embedder = get_embedder()
    if embedder is None:
        print("OPENAI_API_KEY is not set — cannot embed the golden queries.", file=sys.stderr)
        return 1

    print(f"Embedding {len(queries)} golden queries (excluded from timings)...")
    embeddings = {q["id"]: embedder.embed_one(q["query"]) for q in queries}

    # Warm the reranker once so its (one-time) model load does not skew the first
    # timed reranking run.
    print("Warming up the cross-encoder (first load downloads weights)...")
    get_reranker().load()

    results = {cfg[0]: {"precisions": [], "latencies_ms": [], "per_query": {}} for cfg in CONFIGS}
    empty_warning = False

    for cfg_id, _s, _r, search_mode, rerank in CONFIGS:
        for q in queries:
            relevant = set(q["relevant_budget_ids"])
            emb = embeddings[q["id"]]

            # Warm-up (discarded) then measured runs.
            await _run_once(emb, q["query"], search_mode, rerank, settings, k)
            samples = []
            last = None
            for _ in range(MEASURED_RUNS):
                with _Stopwatch() as sw:
                    last = await _run_once(emb, q["query"], search_mode, rerank, settings, k)
                samples.append(sw.elapsed_ms)

            if not last:
                empty_warning = True
            precision = precision_at_k(last, relevant, k)
            results[cfg_id]["precisions"].append(precision)
            results[cfg_id]["latencies_ms"].extend(samples)
            results[cfg_id]["per_query"][q["id"]] = precision

    _print_report(results, queries, k)
    if empty_warning:
        print(
            "\nWARNING: some configurations returned 0 chunks. Is the base corpus "
            "ingested? Run `uv run python scripts/query_examples.py` to ingest it.",
            file=sys.stderr,
        )
    return 0


def _print_report(results: dict, queries: list, k: int) -> None:
    print(f"\n## Retrieval evaluation — precision@{k} and latency\n")
    print(f"| Config | Search | Reranking | Precision@{k} | Latency (ms) |")
    print("| --- | --- | --- | --- | --- |")
    for cfg_id, search_label, rerank_label, _m, _rr in CONFIGS:
        bucket = results[cfg_id]
        mean_p = statistics.fmean(bucket["precisions"])
        mean_l = statistics.fmean(bucket["latencies_ms"])
        print(f"| {cfg_id} | {search_label} | {rerank_label} | {mean_p:.2f} | {mean_l:.1f} |")

    print(f"\n### Per-query precision@{k}\n")
    print("| Query | " + " | ".join(cfg[0] for cfg in CONFIGS) + " |")
    print("| --- | " + " | ".join("---" for _ in CONFIGS) + " |")
    for q in queries:
        row = [q["id"]] + [f"{results[cfg[0]]['per_query'][q['id']]:.2f}" for cfg in CONFIGS]
        print("| " + " | ".join(row) + " |")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
