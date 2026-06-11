# Arquitectura del estimador

Este documento es el **contrato de arquitectura** del servicio. El código de cada sesión
nueva debe respetarlo. Si una pieza no encaja en ninguna capa, primero se decide dónde vive
(y se actualiza este documento), no se crea otra carpeta suelta en la raíz.

## 1. Las tres arquitecturas de IA (y por qué componen)

El estimador no es un único patrón de generación: a lo largo del máster apila tres,
**de forma aditiva**, sobre una base común:

- **CAG — Cache-Augmented Generation** (`app/generation/cag/`). Responde sin tocar el LLM
  cuando ya hay una respuesta equivalente: primero un acierto exacto (SHA-256), luego un
  acierto por similitud vectorial.
- **RAG — Retrieval-Augmented Generation** (`app/generation/rag/`). Convierte un corpus
  (presupuestos históricos) en chunks + embeddings y —a partir de la Sesión 8— los persiste
  y los recupera para enriquecer el prompt con conocimiento citable.
- **Agéntica** (`app/generation/agentic/`). Un bucle Actor-Crítico-Boss que itera y audita la
  estimación antes de aceptarla, apoyado en la conversación multi-turno
  (`app/generation/conversation/`).

**Tesis central**: estas tres capas no se conocen entre sí. **Componen únicamente a través del
conductor** (`app/domain/estimation_service.py`). Esa es la regla que evita que el proyecto
vuelva a degenerar en una sucesión de carpetas acopladas.

## 2. El pastel de capas

```
app/
├── main.py                 # factory FastAPI + lifespan
├── config.py               # settings singleton (get_settings, @lru_cache)
├── dependencies.py         # composition root: wiring de singletons
│
├── foundation/             # plomería sin opinión de arquitectura AI
│   ├── llm/                #   LLMWrapper (LiteLLM + Instructor) + runtime_config.py (overrides de modelo en Redis)
│   ├── prompts/            #   loader Jinja2 + plantillas versionadas (estimation/v1..v3, …)
│   ├── guardrails/         #   input (moderación+injection+PII) / output (filter de scope)
│   ├── attachments/        #   extracción de texto de PDF/DOCX subidos
│   └── persistence/        #   db.py (estimations+chat_sessions, S5) + database.py/models/repos (jobs, mappings, S6) ⟂
│
├── domain/                 # contrato + conductor
│   ├── schemas/            #   EstimationRequest/Result/Response (+ record.py ⟂) — contrato con el cliente
│   └── estimation_service.py  # EstimationService — ÚNICO punto de composición
│
├── generation/             # las 3 arquitecturas que componen + substrato conversacional
│   ├── cag/                #   exact.py + semantic.py
│   ├── rag/                #   chunking/ + embedding/ + analysis/ + store/(S8) + retriever.py(S8)
│   ├── agentic/            #   boss.py + critic.py
│   └── conversation/       #   models, store (DbSessionStore en Postgres ⟂), metadata_extractor, tier_resolver, compression/
│
├── ingestion/              # pipeline batch (offline) que alimenta RAG
│   └── catalog/ loaders/ parsers/ cleaning/ pii/ documents/ orchestrator.py architecture.py
│
└── api/                    # transporte: routers finos, sin lógica de negocio
    ├── estimations.py      #   POST /api/v1/estimate
    ├── records.py          #   /api/v1/estimations/* — CRUD persistido + /run ⟂
    ├── sessions.py         #   /sessions/*
    ├── ingestion.py        #   /api/v1/ingestion/*
    ├── embeddings.py       #   POST /embeddings/ingest + /embeddings/compare
    └── config.py           #   GET/PUT /api/v1/config/models (modelos en runtime)
```

> Las líneas marcadas con **⟂** son **divergencias de esta implementación** respecto al repo
> oficial del profesor (ver §10). Todo lo demás sigue el contrato tal cual.

## 3. Reglas de dependencias (MUST / MUST NOT)

De más-importado a menos. Cada capa **solo** puede importar de las que tiene por encima:

| Capa | PUEDE importar | NO PUEDE importar |
|---|---|---|
| `config.py` | (nada interno) | — |
| `foundation/*` | `config` | `domain`, `generation`, `ingestion`, `api` |
| `domain/schemas/*` | `config`, `foundation` | `generation`, `api` |
| `generation/<x>/*` | `config`, `foundation`, `domain/schemas` | `api`, `dependencies`, **otro hermano de `generation`** |
| `domain/estimation_service.py` (CONDUCTOR) | todos los hermanos de `generation` + `foundation` + `schemas` | `api`, `dependencies` |
| `ingestion/*` | `config`, `foundation`, `domain/schemas`, `generation/rag` | `api`, el conductor |
| `api/*` | `dependencies`, `domain` (schemas + conductor), excepciones de `foundation` | lógica de negocio |
| `dependencies.py` (COMPOSITION ROOT) | cualquier cosa | (lo importan solo `api/` y los tests) |
| `main.py` | `api`, `config` | — |

**Dos aristas especiales, explícitas:**
1. `agentic` **puede** importar `conversation` (lo agéntico se construye sobre el multi-turno).
   La inversa está **prohibida**.
2. Los hermanos de `generation` se encuentran **solo** en el conductor. Si dos capas necesitan
   colaborar, el método que las une va en `EstimationService`, nunca un import cruzado.

## 4. El conductor

`app/domain/estimation_service.py::EstimationService` es el único sitio donde se cablean las
capas. Sus tres entradas y qué tocan:

- `estimate()` — guardrails(in) → **cag** (exacto + semántico) → prompts → **llm** → guardrails(out) → cag.store
- `estimate_conversational()` — **conversation** (historial+metadata+compresión) → prompts → llm → guardrails(out)
- `estimate_with_acb()` — **agentic** (Boss orquesta Actor+Critic sobre la conversación)

Cuando RAG entre en el camino de petición (S8+), el paso de retrieval se añade **aquí**, como
un step más del conductor, no dentro de otra capa.

## 5. Composition root

`dependencies.py` y `config.py` viven en la **raíz**, por encima de las capas, a propósito: el
composition root tiene permiso para alcanzar cualquier capa (es su trabajo cablear), así que no
puede pertenecer a ninguna. Toda fábrica de singletons (`get_llm_wrapper`, `get_cache`,
`get_semantic_cache`, `get_session_store`, los chunkers, `get_estimation_service`) está aquí.

## 6. Camino de la petición principal

```
POST /api/v1/estimate
  └→ app/api/estimations.py                         (HTTP fino, mapeo de errores)
       └→ app/domain/estimation_service.py::estimate()
            1. app/foundation/guardrails/input.py     (moderación + injection + PII)
            2. app/generation/cag/exact.py            (acierto exacto SHA-256)
            3. app/generation/cag/semantic.py         (similitud vectorial redisvl)
            4. app/foundation/prompts/loader.py       (Jinja2 versionado)
            5. app/foundation/llm/wrapper.py          (Instructor + validators + re-prompt)
            6. app/foundation/guardrails/output.py    (filter de scope)
            7. cag.exact.set() + cag.semantic.store()
            8. return EstimationResponse(result, prompt_version, cached)
```

## 7. ¿Dónde va mi código nuevo?

| Si añades… | Va en… |
|---|---|
| Backend LLM, plantilla de prompt, guardrail nuevo | `foundation/` |
| Retrieval, chunking, vector store, embeddings | `generation/rag/` |
| Rol de agente o paso de orquestación | `generation/agentic/` |
| Estrategia de cache | `generation/cag/` |
| Lógica de memoria conversacional | `generation/conversation/` |
| Endpoint HTTP | `api/` (fino) + factory en `dependencies.py` |
| Composición entre capas | método en `EstimationService` (`domain/`), **nunca** import cruzado |
| Fuente de datos / parser / limpieza offline | `ingestion/` |

## 8. Contratos públicos que NO se rompen

- **Rutas HTTP**: `/api/v1/estimate`, `/api/v1/estimations/*` (⟂), `/sessions/*`,
  `/api/v1/ingestion/*`, `/embeddings/ingest`, `/embeddings/compare`, `/api/v1/config/models`.
  El cliente (en este repo, una **SPA Angular** `estimator-frontend/`; en el oficial, Rails
  `estimator-web/`) depende de ellas y de la forma JSON de `EstimationResponse` / `ACBResponse`.
- **`EstimationResult`** (`domain/schemas/estimation.py`): el orden de campos importa para
  Instructor (`phases` antes que `total_cost_eur`/`total_duration_weeks`) y los dos
  `model_validator` (`phases_sum_matches_total`, `low_confidence_requires_out_of_scope_prefix`)
  son las reglas de negocio que disparan el re-prompt.

## 9. Roadmap (slots reservados)

- `generation/rag/store/` — persistencia pgvector (HNSW). **Sesión 8.**
- `generation/rag/retriever.py` — recuperación semántica con filtrado por metadatos/acceso. **Sesión 8.**

## 10. Divergencias de esta implementación (⟂ vs repo oficial)

Este repo es un *fork* de trabajo del proyecto del profesor. Mantenemos a propósito cuatro
desvíos; todos **encajan dentro del contrato de capas** anterior (no lo rompen):

1. **API de estimaciones persistidas** (`api/records.py` + `domain/schemas/record.py`).
   Un CRUD (`/api/v1/estimations/*`) que guarda cada estimación como fila y la ejecuta de
   forma asíncrona (`/run`). El oficial no persiste estimaciones. Es transporte + contrato:
   vive en `api/` + `domain/schemas/`, como manda la tabla.
2. **Doble base de datos** dentro de `foundation/persistence/`. `db.py`/`db_models.py` (S5:
   tablas `estimations` y `chat_sessions`, creadas con `create_all()` al arranque) conviven
   con `database.py`/`models.py`/`repositories/` (S6: `pseudonym_mappings`, `ingestion_jobs`,
   gestionadas por Alembic). Mismo Postgres, dos `Base`. El oficial sólo tiene la segunda.
3. **Memoria conversacional en Postgres** (`DbSessionStore`, no el `SessionStore` en memoria
   del oficial). Por eso `conversation/store.py` importa el ORM de `foundation/persistence/` —
   importación legal: `generation/*` puede importar `foundation`.
4. **Cliente Angular** (`estimator-frontend/`, fuera de este servicio) en lugar del Rails
   `estimator-web/` del oficial. El contrato HTTP es idéntico; la pestaña "Ajustes" que
   consume `/api/v1/config/models` aún no está portada a Angular (la sesión la añadió en Rails).

Detalles menores: el wrapper captura *token usage* y coste también en las llamadas
estructuradas (`create_with_completion`), telemetría que el oficial no recoge en ese camino.
(El driver síncrono se alineó con el oficial en `psycopg` v3 en la Sesión 8.)

> **Consecuencia para el endpoint de config (S7 live):** el switch de modelo en runtime aplica
> a `PRIMARY_MODEL`/`FALLBACK_MODEL` (vía propiedades del wrapper), a los chunkers
> `PROPOSITIONAL`/`CONTEXTUAL` (vía sus *factories*) y —en este repo— también a
> `CRITIC`/`METADATA`/`COMPRESSION` (resueltos como propiedades en `EstimationService`).

## Apéndice — Mapa de migración de rutas (vieja → nueva)

| Antes | Ahora |
|---|---|
| `app/services/estimation.py` | `app/domain/estimation_service.py` |
| `app/services/llm_wrapper.py` | `app/foundation/llm/wrapper.py` |
| `app/services/cache.py` | `app/generation/cag/exact.py` |
| `app/cache/semantic.py` | `app/generation/cag/semantic.py` |
| `app/services/boss.py` | `app/generation/agentic/boss.py` |
| `app/services/critic.py` | `app/generation/agentic/critic.py` |
| `app/guardrails/*` | `app/foundation/guardrails/*` |
| `app/prompts/*` | `app/foundation/prompts/*` |
| `app/attachments/*` | `app/foundation/attachments/*` |
| `app/persistence/*` | `app/foundation/persistence/*` |
| `app/schemas/*` | `app/domain/schemas/*` |
| `app/sessions/*` | `app/generation/conversation/*` |
| `app/embedding_pipeline/base.py` | `app/generation/rag/chunking/base.py` |
| `app/embedding_pipeline/chunker.py` | `app/generation/rag/chunking/structural.py` |
| `app/embedding_pipeline/strategies/*` | `app/generation/rag/chunking/strategies/*` |
| `app/embedding_pipeline/embedder.py` | `app/generation/rag/embedding/embedder.py` |
| `app/embedding_pipeline/{similarity,comparison}.py` | `app/generation/rag/analysis/*` |
| `app/embedding_pipeline/schemas.py` | `app/generation/rag/schemas.py` |
| `app/embedding_pipeline/router.py` | `app/api/embeddings.py` |
| `app/routers/*` | `app/api/*` |
| `app/db.py` ⟂ | `app/foundation/persistence/db.py` |
| `app/db_models.py` ⟂ | `app/foundation/persistence/db_models.py` |
| `app/routers/records.py` ⟂ | `app/api/records.py` |
| `app/schemas/record.py` ⟂ | `app/domain/schemas/record.py` |

> Nota: nuestro `embedding_pipeline/` pre-directo sólo tenía `chunker.py`, `embedder.py`,
> `schemas.py` y `router.py` (no había `base.py` ni `strategies/`). La sesión en vivo añade el
> resto del laboratorio de chunking. Conservamos nuestro `schemas.py` (con `sector` abierto y
> `extra="ignore"`, que nuestro `budgets_sample.json` necesita) y nuestro `embedder.py` (ordena
> la respuesta por `index`); el resto de `rag/` es código nuevo del directo.
