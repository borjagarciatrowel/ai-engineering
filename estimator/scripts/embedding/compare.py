#!/usr/bin/env python
"""CLI: embed two texts and print their cosine similarity (Session 7).

Reuses the project's ``OpenAIEmbedder``. Cosine similarity is computed by hand
with the standard library only — no numpy, no scikit-learn.

Run inside the container:
    docker compose exec estimator python scripts/embedding/compare.py \\
        --text-a "OAuth 2.0 authentication backend for fintech" \\
        --text-b "JWT-based authorization service for banking app"

Run outside the container (with estimator/.env loaded):
    uv run python scripts/embedding/compare.py \\
        --text-a "..." --text-b "..."
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

# Make ``app`` importable regardless of the working directory. This file lives
# at estimator/scripts/embedding/compare.py, so the project root (estimator/,
# which contains the ``app`` package) is three levels up.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from openai import OpenAI  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.embedding_pipeline.embedder import OpenAIEmbedder  # noqa: E402


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Dot product divided by the product of the L2 norms. Pure stdlib."""
    if len(a) != len(b):
        raise ValueError("vectors must have the same dimension")
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Embed two texts and print their cosine similarity."
    )
    parser.add_argument("--text-a", required=True, help="First text")
    parser.add_argument("--text-b", required=True, help="Second text")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    settings = get_settings()
    if not settings.OPENAI_API_KEY:
        print("error: OPENAI_API_KEY is not set (check estimator/.env)", file=sys.stderr)
        return 1

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    embedder = OpenAIEmbedder(client=client, model=settings.EMBEDDING_MODEL)

    vector_a = embedder.embed_one(args.text_a)
    vector_b = embedder.embed_one(args.text_b)
    similarity = cosine_similarity(vector_a, vector_b)

    print(f"Text A: {args.text_a}")
    print(f"Text B: {args.text_b}")
    print(f"Cosine similarity: {similarity:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
