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

## Run the backend in Docker

```bash
cd estimator
docker compose up --build
```

The Angular frontend still runs locally (`npm start`) and proxies to the container on port 8000.

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

- `POST /api/v1/estimate?prompt_version=v1` → `EstimationResponse` (text + metadata)
- `POST /api/v1/estimate/stream?prompt_version=v1` → NDJSON stream of `{"t": "<token>"}` and a final `{"done": true, …}` chunk

### Template tests

`tests/prompts/test_estimation_v1.py` runs in milliseconds and checks:

- The user description is rendered verbatim inside `<project_description>`.
- `output_format=phases_table` adds the `phases_table`/`confidence_pct` keywords; `narrative` does not.
- `detail_level=detailed` adds the "list assumptions per phase" instruction; `summary` does not.
- The `{% include "examples.j2" %}` is wired up.
- Unknown versions raise.
