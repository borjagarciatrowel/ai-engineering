# session_09_live Port + S10 Convergence — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make our FastAPI `estimator/` app identical to the official `session_10` branch — port the full `session_09_live` RAG generation flow + secured endpoints + hardening + task corpus + wizard stage endpoints, and converge the already-committed S10 work onto the official contract. Only the frontend (Rails `estimator-web`) is out of scope.

**Architecture:** Layered RAG. The orchestrator `estimate_from_transcript` runs `transcript → reformulate → embed → retrieve(filtered+threshold+soft-fail, via the S10 hybrid/rerank pipeline) → truncate → assemble(<source> XML) → generate(Estimate via LLMWrapper/Instructor) → validate citations (1 retry) → coherence (1 repair) → idempotency`. Two secured routers expose retrieval and from-transcript; per-stage routers expose each step for a wizard.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy 2.0 async (asyncpg) + pgvector, Instructor/LiteLLM (`LLMWrapper`), tiktoken, slowapi, sentence-transformers (S10), Redis (idempotency/runtime config), structlog, Alembic, uv, pytest (asyncio_mode=auto).

---

## Source of truth & porting rules

This is a **faithful port**. For every file, the canonical content is the official repo:

- **OFICIAL:** `/Users/borjagarciacueto/Documents/Claude/Projects/ai-engineering-oficial/estimator/<path>` (branch `session_10`, already checked out — files are at the combined S9+S10 state we want).
- **NUESTRO:** `/Users/borjagarciacueto/Documents/Claude/Projects/ai-engineering/estimator/<path>`.

Rules for each task:
1. **READ the official file first**, then reproduce it in ours.
2. **NEW file** (not in ours) → copy verbatim. Package paths match (`app.generation.rag.*`, `app.api.*`), so imports need no change.
3. **MODIFIED file** (exists in ours, possibly with our S6/S7/S8/S10 content) → **merge**: add the official S9/S10 additions without deleting our existing content. The diff to apply is `git -C <oficial> show <rev> -- estimator/<path>` (S9-live rev `cb83eb8`, S10 rev `ff6b16b`).
4. Apply the **divergences** (section below) — they are the ONLY intentional differences.
5. Tests are ported faithfully too (mock at the DI boundary; no live LLM/DB).

**Intentional divergences (keep):** single Postgres for the app (the official's 2nd Postgres was for Rails); `DbSessionStore` (our S5 Postgres-backed sessions); no Rails/Angular frontend. Models default `gpt-5`/`gpt-5-mini` as in official.

**Verify-as-you-go:** most unit tests need neither torch nor a live DB (reranker imports torch lazily; store/LLM mocked). Use `cd estimator && uv run --no-sync pytest <paths> -v`. `slowapi` is the only new runtime dep (added in Phase 6 with `uv add slowapi`). The from-transcript endpoint end-to-end (gpt-5) is NOT exercised by tests.

---

## File structure (created / modified)

**Created — RAG flow:** `app/generation/rag/{errors,observability,query_reformulator,context_assembler,prompt_builder,validation,idempotency,estimator}.py`
**Created — API:** `app/api/{security,rate_limiting,deps}.py`, `app/api/routers/{__init__,retrieval,estimate,estimate_stages}.py`
**Created — data/scripts:** `scripts/build_task_corpus.py`, `data/task_corpus.json`
**Created — tests:** `tests/api/{__init__,test_security,test_rate_limiting,test_idempotency,test_estimate_stages}.py`, `tests/generation/{__init__,rag/__init__,rag/test_query_reformulator,rag/test_context_assembler,rag/test_validation,rag/test_estimator,rag/test_retriever,rag/test_structural_chunker}.py`, `tests/test_task_corpus_generator.py`
**Modified:** `app/generation/rag/schemas.py`, `app/generation/rag/store/repository.py`, `app/generation/rag/retrieval/pipeline.py`, `app/generation/rag/retriever.py`, `app/generation/rag/chunking/structural.py`, `app/generation/rag/ingest_service.py`, `app/foundation/llm/{wrapper,runtime_config}.py`, `app/config.py`, `app/dependencies.py`, `app/main.py`, `app/api/{config,embeddings}.py`, `.env.example`, `pyproject.toml`, `scripts/eval_retrieval_s10.py`, `tests/test_hybrid_retrieve.py`, `tests/test_embeddings_ingest_persist.py`

---

## Phase 1 — Contracts (errors + schemas)

### Task 1.1: Port `errors.py`
**Files:** Create `app/generation/rag/errors.py` (from OFICIAL same path).
- [ ] Read OFICIAL `app/generation/rag/errors.py`; copy verbatim (defines `ReformulationError`, `RetrievalError`, `GenerationError`, `MalformedEstimateError`, and any base).
- [ ] Verify import: `cd estimator && uv run --no-sync python -c "import app.generation.rag.errors as e; print(e.RetrievalError, e.GenerationError)"` → prints the classes.
- [ ] Commit: `git add estimator/app/generation/rag/errors.py && git commit -m "feat(rag): add S9 retrieval/generation error types"`

### Task 1.2: Merge S9 schema classes into `schemas.py`
**Files:** Modify `app/generation/rag/schemas.py`.
- [ ] Read OFICIAL `app/generation/rag/schemas.py` (the S9 section: `EstimationQuery`, `RetrievedChunk`, `RetrievalResult`, `SourceCitation`, `Assumption`, `TaskItem`, `WorkModule`, `Estimate`, `RetrievalRequest`, `EstimateRequest`, and the per-stage `ReformulateRequest`/`ReformulationResult`/`AssembleRequest`/`AssembleResult`/`GenerateRequest`/`GenerateResult`; plus the `Scale`/`Confidence`/`Relevance`/`Impact` literals). Append them to ours verbatim (keep our existing `Budget`/`Chunk`/`SearchHit`/etc.).
- [ ] Add `module: str | None = None` to `BudgetComponent` and `chunk_type: str = "budget_component"` to `IngestRequest` (per OFICIAL).
- [ ] Write test `tests/generation/rag/test_schemas_s9.py`: assert `Estimate(confidence="insufficient", reasoning="x")` validates with null totals; `RetrievedChunk(id=1, content="c", sector="finance", project_year=2024, chunk_type="budget_component", distance=0.1)` validates; `RetrievalResult(chunks=[], low_confidence=True, candidates_evaluated=0)` validates. (Create `tests/generation/__init__.py`, `tests/generation/rag/__init__.py`.)
- [ ] Run: `uv run --no-sync pytest tests/generation/rag/test_schemas_s9.py -v` → PASS.
- [ ] Commit: `git add -A estimator/app/generation/rag/schemas.py estimator/tests/generation && git commit -m "feat(rag): add S9 estimation/retrieval schemas (Estimate, RetrievedChunk, ...)"`

---

## Phase 2 — Store `search_filtered` + rewire S10 pipeline

### Task 2.1: Add `ChunkStore.search_filtered`
**Files:** Modify `app/generation/rag/store/repository.py`.
- [ ] Read OFICIAL `app/generation/rag/store/repository.py::search_filtered` + `_structural_filters`. Port both into ours (we already have `search`, `search_lexical`, `find_document_id`, `persist_document_with_chunks`). Add imports it needs (`Integer`, `cast`, `func` — we have `func`; add `Integer`, `cast`). **Divergence:** our `search` uses plain `ChunkRow.embedding.cosine_distance(...)` (no HALFVEC); use the same plain `cosine_distance` in `search_filtered` (drop the `cast(..., HALFVEC(...))` the official uses for its halfvec setup).
- [ ] Write test in `tests/test_rag_store_models.py` or new `tests/generation/rag/test_repository_filters.py`: introspection-only is not enough here; instead assert `_structural_filters` builds the expected predicate count for given args (pure, no DB): e.g. `ChunkStore._structural_filters(sectors=["finance"], project_year_min=2020, project_year_max=None, chunk_types=None)` returns a list of length 2.
- [ ] Run: `uv run --no-sync pytest tests/generation/rag/test_repository_filters.py -v` → PASS.
- [ ] Commit: `git add -A estimator/app/generation/rag/store/repository.py estimator/tests && git commit -m "feat(rag): add metadata-filtered vector search (search_filtered)"`

### Task 2.2: Rewire `retrieval/pipeline.py` to the official contract
**Files:** Modify `app/generation/rag/retrieval/pipeline.py`.
- [ ] Read OFICIAL `app/generation/rag/retrieval/pipeline.py` (the `RetrievalResult`-returning version using `store.search_filtered`). Replace ours with it. Key signature: `retrieve(*, query_embedding, query_text, search_mode="vector", rerank=False, top_k=10, recall_k=50, rerank_top_n=5, distance_threshold=0.6, rrf_k=60, sectors=None, project_year_min=None, project_year_max=None, chunk_types=None, reranker=None) -> RetrievalResult`. It builds `RetrievedChunk` via `_row_to_chunk` (reads `metadata_["client_sector"]`, `["year"]`, `["budget_id"]`), fuses with RRF, reranks via `asyncio.to_thread`, returns `RetrievalResult(chunks, low_confidence=not final, candidates_evaluated)`. Imports `RetrievalError` from `app.generation.rag.errors`.
- [ ] **Divergence:** keep `search_mode`/`rerank` falling back to `settings.RETRIEVAL_SEARCH_MODE`/`RERANKER_ENABLED` when `None` (so the env toggle still works), matching our existing behaviour; everything else verbatim.
- [ ] Rewrite `tests/test_hybrid_retrieve.py` from OFICIAL `tests/generation/rag/test_hybrid_retrieve.py` (asserts on `result.chunks`, `result.low_confidence`, `result.candidates_evaluated`, `chunk.budget_id`; FakeStore exposes `search_filtered` + `search_lexical`). Move it to `tests/generation/rag/test_hybrid_retrieve.py` to match official layout; delete the old flat `tests/test_hybrid_retrieve.py`.
- [ ] Run: `uv run --no-sync pytest tests/generation/rag/test_hybrid_retrieve.py -v` → PASS.
- [ ] Commit: `git add -A estimator/app/generation/rag/retrieval/pipeline.py estimator/tests && git commit -m "refactor(rag): converge S10 pipeline to RetrievalResult/search_filtered (official contract)"`

### Task 2.3: Re-align the S10 eval script
**Files:** Modify `scripts/eval_retrieval_s10.py`.
- [ ] Update `precision_at_k` to read `chunk.budget_id` (now a field on `RetrievedChunk`, not `metadata["budget_id"]`); `_run_once` passes `distance_threshold=NO_FLOOR_THRESHOLD` (2.0) and reads `result.chunks`; mirror OFICIAL `scripts/eval_retrieval_s10.py` (it imports `scripts.s08_common`; since we don't have it, keep our inlined `_Stopwatch` + `get_embedder()`).
- [ ] Syntax check: `uv run --no-sync python -c "import ast; ast.parse(open('scripts/eval_retrieval_s10.py').read()); print('ok')"` → `ok`.
- [ ] Commit: `git add estimator/scripts/eval_retrieval_s10.py && git commit -m "refactor(eval): S10 eval reads RetrievalResult.chunks + budget_id field"`

---

## Phase 3 — Flow modules (pure-ish, mock LLM)

For each: read OFICIAL file, copy verbatim, port its OFICIAL test (`tests/generation/rag/test_*.py`), run, commit. All under `app/generation/rag/`.

### Task 3.1: `observability.py` (`log_stage`)
- [ ] Copy OFICIAL `observability.py` verbatim. (No dedicated official test — covered indirectly.) Smoke: `uv run --no-sync python -c "from app.generation.rag.observability import log_stage; import structlog; \nwith log_stage('x','rid'): pass\nprint('ok')"` → `ok`.
- [ ] Commit: `git commit -am "feat(rag): add per-stage observability (log_stage)"` (after `git add`).

### Task 3.2: `prompt_builder.py`
- [ ] Copy OFICIAL `prompt_builder.py` verbatim (`build_system_prompt`, `build_user_message`).
- [ ] Test `tests/generation/rag/test_prompt_builder.py`: `build_user_message("<sources>..</sources>", EstimationQuery(function="f"))` returns a str containing the context block and the function; `build_system_prompt()` returns a non-empty str.
- [ ] Run that test → PASS. Commit.

### Task 3.3: `query_reformulator.py`
- [ ] Copy OFICIAL `query_reformulator.py` verbatim (`reformulate_query`, `compose_search_text`). It calls `LLMWrapper.complete_structured` (extended in Phase 5) — that's fine; tests mock the wrapper.
- [ ] Port OFICIAL `tests/generation/rag/test_query_reformulator.py` (mocks the wrapper / `get_llm_wrapper`).
- [ ] Run → PASS. Commit.

### Task 3.4: `context_assembler.py`
- [ ] Copy OFICIAL `context_assembler.py` verbatim (`build_context_block`, `truncate_to_token_budget`). Uses a token encoder passed in (tiktoken) + `RetrievedChunk`.
- [ ] Port OFICIAL `tests/generation/rag/test_context_assembler.py` (uses a fake/real encoder; whole-chunk truncation; `<source id=...>` formatting).
- [ ] Run → PASS. Commit.

### Task 3.5: `validation.py`
- [ ] Copy OFICIAL `validation.py` verbatim (`validate_citations`, `check_coherence`).
- [ ] Port OFICIAL `tests/generation/rag/test_validation.py` (fabricated source ids; insufficient-context coherence rule).
- [ ] Run → PASS. Commit.

### Task 3.6: `idempotency.py`
- [ ] Copy OFICIAL `idempotency.py` verbatim (Redis-backed with in-process dict fallback; `get`/`set`; TTL from settings). No official unit test file dedicated — covered by `tests/api/test_idempotency.py` (Phase 6). Smoke import test.
- [ ] Commit.

---

## Phase 4 — Orchestrator

### Task 4.1: `estimator.py`
**Files:** Create `app/generation/rag/estimator.py`.
- [ ] Copy OFICIAL `app/generation/rag/estimator.py` verbatim (`estimate_from_transcript`, `generate_estimate`, `_generate`, `_insufficient`, `_current_request_id`, `_KNOWN_SECTORS`). It imports `get_runtime_retrieval_config`, `get_idempotency_store`, `get_token_encoder`, `get_embedder`, `get_llm_wrapper` from `app.dependencies` (added Phase 5) and `retrieve` from the pipeline (Phase 2).
- [ ] Port OFICIAL `tests/generation/rag/test_estimator.py` (fakes: wrapper, embedder, store/pipeline, idempotency store, token encoder, runtime retrieval config — all via monkeypatching `app.dependencies`). This is the keystone test of the flow (soft-fail short-circuit, citation retry, coherence repair, idempotency hit).
- [ ] Run: `uv run --no-sync pytest tests/generation/rag/test_estimator.py -v` → PASS.
- [ ] Commit: `git commit -am "feat(rag): end-to-end transcript→estimate orchestrator"`

---

## Phase 5 — Config, runtime config, deps, wrapper

### Task 5.1: Extend `config.py` with S9 vars
**Files:** Modify `app/config.py`.
- [ ] Apply OFICIAL `git show ff6b16b -- estimator/app/config.py` S9 additions AND any S9-live ones (`git show cb83eb8 -- estimator/app/config.py`): `RETRIEVAL_API_KEY`, `ESTIMATE_API_KEY`, `REFORMULATION_MODEL`, `GENERATION_MODEL`, `GENERATION_REASONING_EFFORT`, `GENERATION_MAX_TOKENS`, `RETRIEVAL_TOP_K`, `RETRIEVAL_DISTANCE_THRESHOLD`, `MAX_CONTEXT_TOKENS`, `IDEMPOTENCY_TTL`. Keep our existing fields + the S10 block already present.
- [ ] Mirror into `.env.example` (S9 vars), following OFICIAL `.env.example`.
- [ ] Smoke: `uv run --no-sync python -c "from app.config import get_settings as g; s=g(); print(s.GENERATION_MODEL, s.RETRIEVAL_TOP_K, s.IDEMPOTENCY_TTL)"` → prints defaults.
- [ ] Commit: `git commit -am "feat(config): S9 RAG generation + retrieval settings"`

### Task 5.2: Extend `LLMWrapper.complete_structured`
**Files:** Modify `app/foundation/llm/wrapper.py`.
- [ ] Apply OFICIAL `git show cb83eb8 -- estimator/app/foundation/llm/wrapper.py` (+17): support `model_override`, `reasoning_effort`, `max_tokens`, and return `(result, meta)`. Merge into our existing method signature without breaking current callers (the S4 estimate path).
- [ ] Run the existing wrapper test: `uv run --no-sync pytest tests/test_llm_wrapper.py -v` → PASS (no regression). Add a case asserting `complete_structured(..., reasoning_effort="high", max_tokens=64000)` passes those through to the (faked) client and returns a 2-tuple.
- [ ] Commit: `git commit -am "feat(llm): complete_structured supports reasoning_effort/max_tokens + returns meta"`

### Task 5.3: `RuntimeRetrievalConfig`
**Files:** Modify `app/foundation/llm/runtime_config.py`.
- [ ] Apply OFICIAL `git show ff6b16b -- estimator/app/foundation/llm/runtime_config.py` (the `RuntimeRetrievalConfig` class: `from_url`, `effective_search_mode`, `effective_rerank`, Redis-backed with settings fallback). Keep our existing `RuntimeModelConfig`.
- [ ] Test `tests/test_runtime_retrieval_config.py`: with a fakeredis/None client, `effective_search_mode()` falls back to `settings.RETRIEVAL_SEARCH_MODE`; setting an override returns it. (Mirror the style of any existing runtime_config test.)
- [ ] Run → PASS. Commit.

### Task 5.4: Wire `dependencies.py`
**Files:** Modify `app/dependencies.py`.
- [ ] Apply OFICIAL `git show cb83eb8 ff6b16b -- estimator/app/dependencies.py` additions: `get_idempotency_store`, `get_token_encoder` (tiktoken `cl100k_base`), `get_runtime_retrieval_config`. We already have `get_reranker`/`get_chunk_store`/`get_async_session_factory`/`get_embedder`. Keep all ours.
- [ ] Smoke: `uv run --no-sync python -c "from app.dependencies import get_token_encoder, get_idempotency_store, get_runtime_retrieval_config; print(get_token_encoder() is not None)"` → `True`.
- [ ] Commit: `git commit -am "feat(deps): wire idempotency store, token encoder, runtime retrieval config"`

---

## Phase 6 — API layer (routers + hardening)

### Task 6.1: Add `slowapi` dependency
- [ ] `cd estimator && uv add slowapi` (updates pyproject + uv.lock + installs; light, no torch).
- [ ] Commit: `git commit -am "build: add slowapi for per-API-key rate limiting"`

### Task 6.2: `security.py` + `rate_limiting.py` + `deps.py`
**Files:** Create `app/api/security.py`, `app/api/rate_limiting.py`, `app/api/deps.py`.
- [ ] Copy each verbatim from OFICIAL. `security.py` uses `secrets.compare_digest` against `RETRIEVAL_API_KEY`/`ESTIMATE_API_KEY`; `rate_limiting.py` configures slowapi keyed per API key; `deps.py` provides the FastAPI dependencies they need.
- [ ] Port OFICIAL `tests/api/test_security.py` and `tests/api/test_rate_limiting.py` (create `tests/api/__init__.py`).
- [ ] Run: `uv run pytest tests/api/test_security.py tests/api/test_rate_limiting.py -v` → PASS.
- [ ] Commit: `git commit -am "feat(api): constant-time API-key auth + per-key rate limiting"`

### Task 6.3: Routers — retrieval, estimate, estimate_stages
**Files:** Create `app/api/routers/{__init__,retrieval,estimate,estimate_stages}.py`.
- [ ] Copy each verbatim from OFICIAL. `retrieval.py` → `POST /v1/retrieval/search` (auth, 120/min, calls `pipeline.retrieve`, maps `RetrievalResult`); `estimate.py` → `POST /v1/estimate/from-transcript` (auth, 10/min, idempotent, calls `estimate_from_transcript`); `estimate_stages.py` → the 4 stage endpoints reusing the pure functions.
- [ ] Port OFICIAL `tests/api/test_estimate_stages.py` (+ any retrieval/estimate router tests; mock the orchestrator/pipeline via dependency overrides).
- [ ] Run: `uv run pytest tests/api -v` → PASS.
- [ ] Commit: `git commit -am "feat(api): secured retrieval + from-transcript + wizard stage routers"`

### Task 6.4: `main.py` + `api/config.py` + `api/embeddings.py`
**Files:** Modify `app/main.py`, `app/api/config.py`, `app/api/embeddings.py`.
- [ ] Apply OFICIAL `main.py` additions: register the new routers + the `X-Request-ID` correlation middleware. Apply `api/config.py` additions: `PUT /api/v1/config/retrieval` (runtime retrieval config). Apply `api/embeddings.py` (+1: pass `chunk_type` through to ingest).
- [ ] Run: `uv run pytest tests/test_health.py -v` and `uv run python -c "from app.main import app; print([r.path for r in app.routes if 'v1' in r.path])"` → lists `/v1/retrieval/search`, `/v1/estimate/from-transcript`, the stage paths.
- [ ] Commit: `git commit -am "feat(api): register S9 routers + X-Request-ID middleware + config/retrieval endpoint"`

---

## Phase 7 — Task-granular corpus

### Task 7.1: `chunking/structural.py` + `ingest_service.py` (module/chunk_type)
**Files:** Modify both.
- [ ] Apply OFICIAL diffs (`structural.py` +3: surface `module` in component metadata; `ingest_service.py` +8: accept/stamp `chunk_type`).
- [ ] Run: `uv run --no-sync pytest tests/test_embeddings_ingest_persist.py -v` after applying the OFICIAL update to that test → PASS. Add/port `tests/generation/rag/test_structural_chunker.py` from OFICIAL.
- [ ] Commit: `git commit -am "feat(rag): surface module metadata + chunk_type in ingest"`

### Task 7.2: `build_task_corpus.py` + `data/task_corpus.json`
**Files:** Create `scripts/build_task_corpus.py`, `data/task_corpus.json`.
- [ ] Copy OFICIAL `scripts/build_task_corpus.py` verbatim. Regenerate `data/task_corpus.json` by running it (deterministic) OR copy the OFICIAL `data/task_corpus.json` verbatim. Prefer copying the official JSON to guarantee byte-parity.
- [ ] Port OFICIAL `tests/test_task_corpus_generator.py`.
- [ ] Run: `uv run --no-sync pytest tests/test_task_corpus_generator.py -v` → PASS.
- [ ] Commit: `git commit -am "feat(data): task-granular synthetic corpus + generator"`

### Task 7.3: `retriever.py` S9 changes
**Files:** Modify `app/generation/rag/retriever.py`.
- [ ] Apply OFICIAL `git show cb83eb8 -- estimator/app/generation/rag/retriever.py` (+94). Read it first to see exactly what it adds (likely a filtered `search_chunks` used by the retrieval router or kept for parity). Merge keeping our existing `SemanticRetriever.search`.
- [ ] Port OFICIAL `tests/generation/rag/test_retriever.py`.
- [ ] Run: `uv run --no-sync pytest tests/generation/rag/test_retriever.py -v` → PASS.
- [ ] Commit: `git commit -am "feat(rag): S9 retriever changes"`

---

## Phase 8 — Final verification

### Task 8.1: Full suite + lint + lock
- [ ] `cd estimator && uv run pytest -q` → all green (262 prior + all new). Investigate/fix any failure before proceeding.
- [ ] `uv run ruff check .` → All checks passed (fix any lint).
- [ ] `uv run ruff format --check .` (or `format`) consistent.
- [ ] Confirm `uv.lock` consistent: `uv lock --check` (or `uv sync --frozen`).
- [ ] Commit any fixups.

### Task 8.2: Update the S10 exercise doc
**Files:** Modify `docs/session-10-rag-recuperacion-avanzada/session-10-exercise-reranking-busqueda-hibrida.md`.
- [ ] Update the "Divergencias" section: the `SearchHit`-vs-`RetrievedChunk` and `search`-vs-`search_filtered` rows move from "divergencia" to "resuelto — convergido al contrato oficial tras portar S9-live". Note the pipeline now returns `RetrievalResult`.
- [ ] Commit: `git commit -am "docs(estimator): S10 exercise — note convergence to official retrieval contract after S9-live port"`

### Task 8.3: Memory + parity spot-check
- [ ] Spot-check parity: `for f in app/generation/rag/estimator.py app/generation/rag/retrieval/pipeline.py app/api/routers/estimate.py; do diff <(sed 's/[[:space:]]*$//' ../../ai-engineering-oficial/estimator/$f) <(sed 's/[[:space:]]*$//' $f) && echo "PARITY $f" || echo "DIFF $f (expected if divergence)"; done` — differences should be only the documented divergences.
- [ ] Update the memory note `estimator-session10-exercise.md` / add `estimator-session09-live-port.md` recording completion.

---

## Self-review notes (author)

- **Spec coverage:** every section of the spec maps to a phase (F1→P1, F2→P2, F3→P3, F4→P4, F5→P5, F6→P6, F7→P7, F8→P8). ✓
- **Live limits:** from-transcript end-to-end (gpt-5) and the A/B/C/D measurement are NOT run by tests — explicitly out, as in the spec. ✓
- **Divergences applied where they bite:** pipeline `None→settings` fallback (2.2), plain `cosine_distance` not halfvec (2.1), single Postgres/DbSessionStore untouched. ✓
- **Risk:** `retriever.py` (+94) content unknown until read — Task 7.3 reads-then-ports; if it duplicates pipeline logic, prefer the pipeline and keep retriever minimal. Flagged.
