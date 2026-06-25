# Spec — Incorporar `session_09_live` (+ converger S10) al repo, paridad con el oficial

**Fecha:** 2026-06-25 · **Rama:** `session-10` · **Repo oficial de referencia:** `ai-engineering-oficial` rama `session_10` (estado combinado S9-live + S10, commit `cb83eb8` para el delta S9-live, `ff6b16b` para S10).

## 1. Objetivo

El `app/` de FastAPI (`estimator/`) debe quedar **idéntico al oficial `session_10`**, salvo el frontend. Esto significa:
- Portar **todo** el changeset de `session_09_live` (flujo RAG de generación + endpoints + hardening + corpus task-granular + endpoints por-etapa del wizard).
- **Converger** el trabajo de S10 ya commiteado (commit `304743b`) al oficial: re-cablear el pipeline híbrido/rerank sobre `RetrievalResult`/`RetrievedChunk`/`search_filtered`, y añadir lo que en S10 habíamos aplazado (`RuntimeRetrievalConfig`, endpoint `config/retrieval`).
- **Sin simplificaciones ni aplazamientos.**

## 2. Estado de partida

- Tenemos: base S8 (`SemanticRetriever`, `ChunkStore.search`, `SearchHit`/`SearchResponse`, store async asyncpg) + S10 con divergencias (pipeline devuelve `list[SearchHit]`, usa `search` no `search_filtered`, sin `RetrievedChunk`/`RetrievalResult`, sin `RuntimeRetrievalConfig`, sin `estimate_stages`).
- Nos falta: **todo** `session_09_live` (el flujo `transcript → reformulate → retrieve → assemble → generate → validate`, los routers seguros, idempotencia, rate-limit, el esquema `Estimate`, el corpus task-granular).

## 3. Inventario a portar (oficial `estimator/`, fiel)

### 3.1 Capa RAG — `app/generation/rag/`
- **Nuevos:** `query_reformulator.py`, `context_assembler.py`, `prompt_builder.py`, `validation.py`, `errors.py` (`ReformulationError`/`RetrievalError`/`GenerationError`/`MalformedEstimateError`), `observability.py` (`log_stage`), `idempotency.py` (Redis o dict in-process), `estimator.py` (orquestador `estimate_from_transcript` + `generate_estimate`).
- **Modificados:** `schemas.py` (+ `EstimationQuery`, `RetrievedChunk`, `RetrievalResult`, `SourceCitation`, `Assumption`, `TaskItem`, `WorkModule`, `Estimate`, `RetrievalRequest`, `EstimateRequest`, + los Request/Result por-etapa, + `module` en `BudgetComponent`, + `chunk_type` en `IngestRequest`), `retriever.py` (cambios S9), `store/repository.py` (`search_filtered`), `chunking/structural.py` (campo `module`), `ingest_service.py` (`chunk_type`).
- **Rewire S10:** `retrieval/pipeline.py` → devolver `RetrievalResult` con `RetrievedChunk`, usar `store.search_filtered` (filtros `sectors`/`project_year_*`/`chunk_types` + `distance_threshold` + `candidates_evaluated`) y `search_lexical`, parámetros `sectors`/`distance_threshold` como el oficial.

### 3.2 Capa API — `app/api/`
- **Nuevos:** `routers/__init__.py`, `routers/retrieval.py` (`POST /v1/retrieval/search`), `routers/estimate.py` (`POST /v1/estimate/from-transcript`), `routers/estimate_stages.py` (`POST /v1/estimate/stages/{reformulate,retrieve,assemble,generate}`), `security.py` (`secrets.compare_digest`), `rate_limiting.py` (slowapi), `deps.py`.
- **Modificados:** `config.py` (endpoint runtime `PUT /api/v1/config/retrieval`), `embeddings.py` (+1), `main.py` (registro de routers + middleware `X-Request-ID`).

### 3.3 Foundation / composición
- `app/foundation/llm/runtime_config.py` → `RuntimeRetrievalConfig` (Redis).
- `app/foundation/llm/wrapper.py` → extensión de `complete_structured` (`model_override`/`reasoning_effort`/`max_tokens` → `(estimate, meta)`).
- `app/config.py` → vars S9: `RETRIEVAL_API_KEY`, `ESTIMATE_API_KEY`, `REFORMULATION_MODEL` (gpt-5-mini), `GENERATION_MODEL` (gpt-5), `GENERATION_REASONING_EFFORT`, `GENERATION_MAX_TOKENS`, `RETRIEVAL_TOP_K`, `RETRIEVAL_DISTANCE_THRESHOLD`, `MAX_CONTEXT_TOKENS`, `IDEMPOTENCY_TTL`.
- `app/dependencies.py` → `get_idempotency_store`, `get_token_encoder` (tiktoken), `get_runtime_retrieval_config`, wiring del orquestador/routers.
- `.env.example` → vars S9. `pyproject.toml` + `uv.lock` → `slowapi` (+ lo de S10 ya añadido).

### 3.4 Datos + scripts
- `data/task_corpus.json` (corpus task-granular sintético) + `scripts/build_task_corpus.py` (generador determinista).

### 3.5 Tests (espejo del oficial, mock en el límite de DI)
- `tests/api/{__init__,test_security,test_rate_limiting,test_idempotency,test_estimate_stages}.py`
- `tests/generation/{__init__,rag/__init__,rag/test_query_reformulator,rag/test_context_assembler,rag/test_validation,rag/test_estimator,rag/test_retriever,rag/test_structural_chunker}.py`
- `tests/test_task_corpus_generator.py`; actualizar `tests/test_embeddings_ingest_persist.py`.
- Re-alinear los tests S10 al nuevo contrato: `tests/test_hybrid_retrieve.py` (→ `RetrievalResult`/`.chunks`/`.budget_id`), `eval_retrieval_s10.py` (lee `.budget_id`, umbral desactivado).

## 4. Reglas de adaptación

1. **Contenido fiel al oficial.** Donde un fichero es nuevo, se copia del oficial. Donde se modifica un fichero que ya tenemos, se **entrelazan** las adiciones S9/S10 con nuestro contenido existente (sin perder lo nuestro de S6/S7/S8).
2. **Modelos:** `gpt-5` / `gpt-5-mini` como el profesor (conmutables por `runtime_config`/`.env`).
3. **Estructura:** se introduce `app/api/routers/` (subpaquete) como el oficial.
4. **Sin frontend.** `estimator-web` (Rails) NO se porta; la integración Angular es trabajo aparte.

## 5. Divergencias residuales (preexistentes, fuera de este port)

1. **Postgres único** sirviendo el FastAPI (el 2º Postgres del oficial era para Rails). El código de app (`DATABASE_URL`, migraciones, modelos) es idéntico; solo cambia a qué contenedor apunta en compose.
2. **`DbSessionStore`** (sesiones conversacionales en Postgres, divergencia de S5). S9 no lo toca.
3. **Frontend Angular** en vez de Rails `estimator-web`.

Todo lo demás del `app/` de FastAPI converge al oficial.

## 6. Fases de implementación (incrementales, `uv run pytest` verde al cerrar cada fase)

- **F1 — Contratos:** `errors.py` + adiciones a `schemas.py` (todas las clases S9) + `module`/`chunk_type`. (tests de schema)
- **F2 — Store + rewire pipeline S10:** `store.search_filtered`; `retrieval/pipeline.py` → `RetrievalResult`/`RetrievedChunk`; actualizar `eval_retrieval_s10.py` + `tests/test_hybrid_retrieve.py`. (introspección + pipeline tests)
- **F3 — Módulos del flujo:** `query_reformulator`, `context_assembler`, `prompt_builder`, `validation`, `observability`, `idempotency`; extensión `wrapper.complete_structured`. (tests unitarios espejo)
- **F4 — Orquestador:** `estimator.py` (`estimate_from_transcript`, `generate_estimate`). (`test_estimator` con fakes)
- **F5 — Config/runtime:** vars en `config.py`/`.env.example`, `RuntimeRetrievalConfig`, `get_idempotency_store`/`get_token_encoder`/`get_runtime_retrieval_config`, endpoint `config/retrieval`.
- **F6 — API:** `security.py`, `rate_limiting.py`, `deps.py`, `routers/{retrieval,estimate,estimate_stages}.py`, `main.py` (routers + middleware), `slowapi` en deps. (tests api)
- **F7 — Corpus task-granular:** `build_task_corpus.py` + `data/task_corpus.json` + `test_task_corpus_generator`; ajustar `ingest_service`/`structural` + `test_embeddings_ingest_persist`.
- **F8 — Verificación final:** suite completa verde, `ruff` limpio, `uv lock` consistente, actualizar el doc del ejercicio S10 (la divergencia "SearchHit/search" pasa a "resuelta: convergido a `RetrievedChunk`/`search_filtered`").

## 7. Verificación y límites

- Los tests unitarios **no** requieren LLM ni DB reales (se mockea en el límite de DI, como el oficial). Meta: toda la suite verde (262 actuales + los nuevos S9).
- El endpoint `POST /v1/estimate/from-transcript` end-to-end (reformulación + generación con gpt-5) **no** se ejecuta en tests — necesita `OPENAI_API_KEY` + stack vivo. Igual que la medición A/B/C/D de S10, queda para ejecución manual.
- `uv lock` ya trae `sentence-transformers`; añadir `slowapi`.
