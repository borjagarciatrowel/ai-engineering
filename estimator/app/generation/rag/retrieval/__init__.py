"""Session 10 retrieval enhancements: hybrid search (RRF) + cross-encoder reranking.

The Session-8 baseline (``SemanticRetriever`` + ``ChunkStore.search``) finds good
candidates by dense cosine k-NN but orders them only roughly and is blind to exact
terms. This package adds the two techniques the Session-10 exercise measures:

* ``reciprocal_rank_fusion`` — fuse the dense and lexical rankings by position.
* ``CrossEncoderReranker`` — rescore ``(query, document)`` pairs jointly.
* ``retrieve`` — the recall-then-rerank pipeline that composes the four measured
  configurations (vector/hybrid × rerank on/off).
"""

from app.generation.rag.retrieval.fusion import reciprocal_rank_fusion
from app.generation.rag.retrieval.pipeline import retrieve
from app.generation.rag.retrieval.reranker import CrossEncoderReranker

__all__ = ["reciprocal_rank_fusion", "retrieve", "CrossEncoderReranker"]
