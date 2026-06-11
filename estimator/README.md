# Estimator – AI software project estimator

AI-powered software estimator with a typed Angular form (Material) and a FastAPI service that renders versioned Jinja2 prompt templates against an OpenAI / Anthropic provider.

```
ai-engineering/
├── estimator/             ← FastAPI service (this folder)
│   ├── app/
│   │   ├── prompts/       ← Jinja2 templates + loader (v1, …)
│   │   ├── routers/       ← /api/v1/estimate{,/stream}
│   │   ├── schemas/       ← typed EstimationRequest with enums
│   │   └── services/      ← OpenAI / Anthropic wrapper
│   └── tests/
└── estimator-frontend/    ← Angular 19 + Angular Material UI
```

## Prerequisites

- Python 3.11+ with [uv](https://docs.astral.sh/uv/) installed
- Node.js 20+ and npm
- `OPENAI_API_KEY` and/or `ANTHROPIC_API_KEY` set in `estimator/.env`

`.env` example:

```env
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=sk-...
```

## Run locally (recommended)

Two terminals.

**Terminal A — FastAPI service:**

```bash
cd estimator
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal B — Angular frontend:**

```bash
cd estimator-frontend
npm install        # only first time
npm start          # serves on http://localhost:4200, proxies /api to :8000
```

Open <http://localhost:4200>.

## Run with Docker (independent stacks)

Each project has its own `docker-compose.yml`. Start them separately:

```bash
# Backend on http://localhost:8000
cd estimator
docker compose up --build

# Frontend on http://localhost:4200 (in another terminal)
cd estimator-frontend
docker compose up --build
```

The Angular container proxies `/api` **and `/sessions`** to
`host.docker.internal:8000`, so the backend stack can be started, stopped, or
replaced (e.g. local `uvicorn` instead of Docker) without touching the frontend
stack.

> After changing `pyproject.toml` (Session 5 added `python-multipart`, `pypdf`,
> `python-docx`), rebuild the backend image: `docker compose up -d --build`. The
> new deps live in the image, not in the bind-mounted `./app`.

## Running tests

Backend (template tests + endpoint tests):

```bash
cd estimator
uv run pytest -q
```

Frontend:

```bash
cd estimator-frontend
npm test            # Karma + Jasmine
```

## Architecture notes

### Typed request

`EstimationRequest` (`app/schemas/estimation.py`) is the only contract between the Angular form and the AI service. The four fields — `description`, `project_type`, `detail_level`, `output_format` — are enums backed by Pydantic v2 and TypeScript types in `estimator-frontend/src/app/models/estimation.ts`.

### Versioned prompt templates

Prompts live as files under `app/prompts/estimation/v1/`:

- `system.j2` – role, format and detail-level conditionals, `{% include "examples.j2" %}`
- `user.j2` – wraps the user's project description in a `<project_description>` block
- `examples.j2` – three few-shot estimations

`render_estimation_prompt(request, version="v1")` returns the `(system, user)` tuple. Adding a `v2/` folder + `?prompt_version=v2` query param is enough to roll out a new template without touching the rest of the code.

### Endpoints

- `POST /api/v1/estimate` → `EstimationResponse` (stateless, structured output)
- `GET|POST|PATCH|DELETE /api/v1/estimations…` → persisted estimation CRUD + `/{id}/run`
- `POST /sessions` → create a session + its estimation row → `{"session_id", "estimation_id"}`
- `GET  /sessions/{id}` → debug view (project_metadata + history length)
- `GET  /sessions/{id}/conversation` → full turn-by-turn history (used by the detail view)
- `POST /sessions/{id}/estimate` → one conversational turn (`multipart/form-data`)
- `POST /embeddings/ingest` → chunk + embed **+ persist** one budget as a `document` + its `chunks` (one transaction) → `IngestResponse` (`document_id`, `chunks_created`, `embedding_dimension`, `ingestion_time_ms`); **409** if a document with that `source_path` already exists (Session 8)
- `POST /search` → embed the query, return the **k nearest chunks by cosine distance** over the persisted corpus (Session 8)

### Conversational memory & attachments (Session 5)

The estimator keeps **conversational memory** per session and accepts **attachments**.
See [`docs/cambios-sesion-05.md`](docs/cambios-sesion-05.md) for the full change log and
[`docs/codigo-explicado.md`](docs/codigo-explicado.md) §17 for the annotated walkthrough.

- **History vs memory.** `ConversationHistory` (`app/sessions/models.py`) is the rolling
  `messages` array with a **sliding window** (`MAX_CONVERSATION_TURNS=6` pairs; oldest
  dropped). `ProjectMetadata` is the durable set of facts (name, team size, technologies,
  agreed scope) kept **apart** from the history and injected into the v2 system prompt every
  turn — so the model remembers context evicted by the window.

- **Attachments — Camino B (local extraction).** We chose **Camino B**: PDF/DOCX text is
  extracted *inside* the service (`pypdf` / `python-docx`, `app/attachments/extractor.py`)
  and concatenated into the transcript with explicit fences
  (`--- attachment: file.pdf ---`). Rationale: keeps the LLM wrapper provider-agnostic
  (text in, text out) and sets up chunking/RAG for module 3. The alternative (Camino A,
  uploading the binary to a multimodal Files API) couples us to one provider.

- **`project_metadata` extraction — LLM extractor.** After each turn a **second, cheap LLM
  call** (`METADATA_EXTRACTOR_MODEL=gpt-4o-mini`, `app/sessions/metadata_extractor.py`)
  returns a structured `ProjectMetadata`, merged with the previous one (scalars overwrite,
  technology list unions). We picked the LLM extractor over a regex heuristic because it is
  far more robust (synonyms, capitalisation, scope summaries); the extra small call per turn
  is acceptable, and a failed extraction falls back to the previous metadata.

- **Persistence — DB instead of an in-memory dict (deliberate deviation).** The brief says a
  process-memory dict is enough. We instead persist sessions to **Postgres** (`chat_sessions`
  table; `DbSessionStore` in `app/sessions/store.py`) so memory survives restarts and is
  shared across workers. `history` and `project_metadata` are stored as JSON columns.

- **Conversational estimations show in the grid.** Each turn also upserts a row in the
  `estimations` table (one row per session, keyed by `estimations.session_id`, refreshed every
  turn), so an estimation made in the conversational UI appears in the estimations landing
  grid alongside the stateless ones.

- **Unified UI: an estimation IS a conversation.** The Angular client has a single flow —
  "Nueva estimación" starts a conversation, and the estimation detail (`/estimations/{id}`)
  *is* the conversational interface (turn thread + composer to add turns + live
  project_metadata panel). The separate chat page and the single-shot edit/run form were
  removed; legacy stateless estimations (no `session_id`) render read-only.

### Embeddings + chunking pipeline (Session 7)

A minimal end-to-end pipeline that turns normalised historical budgets (JSON)
into embedding vectors. Lives in [`app/embedding_pipeline/`](app/embedding_pipeline/).
See [`docs/session-07.md`](docs/session-07.md) for the full walkthrough.

- **Chunking strategy — one component = one chunk.** `JSONStructuralChunker`
  (`app/embedding_pipeline/chunker.py`) trusts the document structure: no
  fixed-size or overlap splitting. Each chunk's embedded `text` is a *contextual
  chunk header* (parent project, sector, year, main tech) followed by the
  component detail, so a chunk never loses the trace of which client/sector it
  belongs to. `token_count` is measured with `tiktoken` for the same model that
  embeds the text, to flag oversized chunks before paying for an API call.
- **Embedder — batched + retrying.** `OpenAIEmbedder`
  (`app/embedding_pipeline/embedder.py`) embeds with `text-embedding-3-small`
  (1536 dims), sends up to 100 chunks per `embeddings.create` call, retries
  `RateLimitError` with 1s/2s/4s backoff and logs each batch via structlog. The
  cost estimate uses a clearly labelled module constant ($0.02 / 1M input
  tokens).
- **Endpoint.** `POST /embeddings/ingest` (`app/embedding_pipeline/router.py`):
  body is `{"budgets": [...]}`, response is the vectorised chunks plus aggregate
  `stats` (`total_budgets`, `total_chunks`, `total_tokens`, `estimated_cost_usd`).
  Visible and invokable from `/docs`. Sample input: [`data/budgets_sample.json`](data/budgets_sample.json).
- **No persistence yet.** Vectors are generated in memory and returned over
  HTTP. PostgreSQL + pgvector persistence arrives in Session 8.

**Invoke the endpoint** (sample data):

```bash
# from estimator/, service running on :8000
curl -s -X POST http://localhost:8000/embeddings/ingest \
  -H "Content-Type: application/json" \
  -d "{\"budgets\": $(cat data/budgets_sample.json)}" | python -m json.tool | head
```

…or open `http://localhost:8000/docs`, expand `POST /embeddings/ingest`, paste
the contents of `data/budgets_sample.json` wrapped in `{"budgets": [...]}` and
hit *Execute*.

**`compare.py` — cosine similarity of two texts.** Two ways to run it:

```bash
# Inside the container
docker compose exec estimator python scripts/embedding/compare.py \
  --text-a "OAuth 2.0 authentication backend for fintech" \
  --text-b "JWT-based authorization service for banking app"

# Outside the container (estimator/.env must hold a funded OPENAI_API_KEY)
uv run python scripts/embedding/compare.py \
  --text-a "OAuth 2.0 authentication backend for fintech" \
  --text-b "JWT-based authorization service for banking app"
```

The three-pair sanity check lives in
[`scripts/embedding/SANITY_CHECK.md`](scripts/embedding/SANITY_CHECK.md).

### Template tests

`tests/prompts/test_estimation_v1.py` runs in milliseconds and checks:

- The user description is rendered verbatim inside `<project_description>`.
- `output_format=phases_table` adds the `phases_table`/`confidence_pct` keywords; `narrative` does not.
- `detail_level=detailed` adds the "list assumptions per phase" instruction; `summary` does not.
- The `{% include "examples.j2" %}` is wired up.
- Unknown versions raise.

### pgvector persistence + semantic search (Session 8)

The Session 7 pipeline stopped at "generate vectors in memory and return them over HTTP".
Session 8 **persists** the corpus in PostgreSQL + `pgvector` and exposes semantic search.
`POST /embeddings/ingest` now stores one budget as a `document` plus its embedded `chunks`
in a single transaction (409 on duplicate `source_path`); `POST /search` returns the *k*
nearest chunks by cosine distance. Full walkthrough in
[`docs/session-08.md`](docs/session-08.md); annotated code in
[`docs/codigo-explicado.md`](docs/codigo-explicado.md) §22.

Run the smoke test against the bundled corpus (15 budgets) and capture the output:

```bash
docker compose up -d                                    # postgres + estimator (alembic runs on boot)
docker compose run --rm estimator python scripts/query_examples.py | tee output_examples.txt
```

The committed [`output_examples.txt`](output_examples.txt) is a real run over
`data/budgets_sample.json`.

**Four schema decisions (the ones the exercise asks us to defend):**

1. **Two tables, not one.** A budget produces N chunks. A single flat table would duplicate
   every document-level field (source, type, sector, year) on each chunk row and lose
   referential integrity. `documents` (1) → `chunks` (N) with `ON DELETE CASCADE` means
   deleting a budget removes its chunks automatically — integrity instead of denormalised
   duplication.

2. **`metadata` as `JSONB`, not columns.** Stable, queried-by-everyone fields
   (`document_type`, `chunk_type`, timestamps) are typed columns. The *open-ended*
   enrichment the chunker attaches (sector, technologies, hours, scope…) lives in a `JSONB`
   column with a **GIN index**, so we can filter by an arbitrary key
   (`metadata->>'client_sector' = 'fintech'`) **without a migration per new key**. Schema
   stability where it matters, flexibility where the vocabulary is still moving.

3. **`cosine_distance` (`<=>`), not L2 or inner product.** OpenAI embeddings are normalised,
   so cosine / inner-product would rank identically — but cosine is the RAG-literature
   convention **and** it matches the `vector_cosine_ops` operator class of the HNSW index we
   add live. If the query operator and the index's operator class disagree, Postgres
   **silently ignores the index** and falls back to a sequential scan. Picking cosine now
   keeps that door open.

4. **No vector index — on purpose (yet).** The migration creates the relational indexes
   (FK, `chunk_type`, GIN on metadata) but **no HNSW/IVFFlat**. The sequential scan is the
   **baseline** the live session measures the index against. At this corpus size (tens of
   documents, dozens of chunks) a seq-scan answers in a few hundred ms — perfectly fine, and
   observing that latency *without* an index is one of the live session's starting points.
