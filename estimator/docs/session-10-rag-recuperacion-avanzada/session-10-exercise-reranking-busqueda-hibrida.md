# Sesión 10 — Ejercicio resuelto: búsqueda híbrida + reranking

> Resolución del ejercicio previo a la Sesión 10 ("Técnicas avanzadas de recuperación 🔴").
> Resuelto **igual que el profesor** (rama oficial `session_10`, commit `ff6b16b`), **adaptado a las divergencias de nuestro repo**.
> Alcance del enunciado: **solo búsqueda híbrida y reranking** (NO expansión de consultas, NO routing multi-índice, NO filtrado por metadatos — eso se construye en la sesión en vivo).

---

## 0. Punto de partida y estrategia

El enunciado asume "el pipeline RAG de la sesión anterior, funcionando" + un wrapper de cross-encoder ya provisto. **Nuestro repo diverge**: nunca portamos la Sesión 9 *live* (no existen `estimator.py`, `query_reformulator.py`, `search_filtered`, `RetrievalResult`, ni los endpoints `/v1/...`). Estamos sobre la **base de la Sesión 8**: `SemanticRetriever` + `ChunkStore.search` (k-NN coseno asíncrono sobre `chunks`), `SearchHit`/`SearchResponse` como contrato.

Decisión: **portar el *delta* de la Sesión 10 del profesor sobre nuestra base S8**, no reconstruir la S9. Todo lo que mide el ejercicio (precision@5 + latencia de las 4 configuraciones) vive en la **capa de recuperación**, así que no hace falta el flujo de generación de la S9. La búsqueda vectorial de la rama densa usa nuestro `ChunkStore.search` (S8) en lugar del `search_filtered` (S9) del oficial — lo cual además respeta el alcance del enunciado: **el filtrado por metadatos está explícitamente fuera**.

---

## 1. Paso 1 — Búsqueda full-text en PostgreSQL

**Migración Alembic `0003_session10_fts`** (`alembic/versions/0003_session10_fts.py`, `down_revision="0002_session8_pgvector"`):

```sql
ALTER TABLE chunks ADD COLUMN content_tsv tsvector
  GENERATED ALWAYS AS (to_tsvector('english', content)) STORED;
CREATE INDEX ix_chunks_content_tsv ON chunks USING gin (content_tsv);
```

- **Columna generada `STORED`**: Postgres recalcula el `tsvector` en cada insert/update de `content` — sin triggers, sin posibilidad de que el índice léxico se desincronice del texto.
- **`'english'`, no `'spanish'`** (igual que el profesor): el enunciado dice "español", pero el dataset real (`data/budgets_sample.json`) **está en inglés** ("Mobile banking API…", "Headless e-commerce storefront…"). El stemming y las stop-words inglesas son las que de verdad suben el recall léxico aquí. Cambiar a `'spanish'` sería tocar el regconfig en dos sitios (la migración y `plainto_tsquery`) — mantenidos consistentes a propósito.
- **Reflejo en el ORM** (`store/models.py`): columna `content_tsv: Mapped[str | None]` con `Computed("to_tsvector('english', content)", persisted=True)` (read-only a nivel ORM) + el índice GIN en `__table_args__`.

## 2. Paso 2 — Rama léxica + fusión RRF (búsqueda híbrida)

**Rama léxica** (`store/repository.py::ChunkStore.search_lexical`): `plainto_tsquery('english', query)` → `@@` para filtrar coincidencias → `ts_rank_cd` (cover density, mayor = mejor) para ordenar. Sin filtros estructurales (fuera de alcance). Devuelve `list[Row]` con `id, document_id, chunk_type, content, metadata_, rank`.

**Fusión RRF** (`app/generation/rag/retrieval/fusion.py`, portada literal): función pura

```
rrf_score(d) = Σ 1 / (k + rank_i(d))        # k=60 por defecto (Cormack et al.)
```

Fusiona **por posición, no por puntuación** — esquiva el problema de que la distancia coseno (menor = mejor) y `ts_rank_cd` (mayor = mejor) viven en escalas incomparables. Recibe *una lista de rankings* (generaliza a N fuentes), devuelve `(chunk_id, score)` ordenado, con desempate determinista por id ascendente.

**Pipeline híbrido** (`retrieval/pipeline.py::retrieve`): lanza la rama densa (`store.search`) y, en modo `hybrid`, la léxica (`store.search_lexical`); construye el pool de candidatos (la distancia vectorial gana sobre el centinela léxico `1.0`); fusiona con RRF. La constante `k` de RRF es parametrizable (`rrf_k`, default `RRF_K=60`).

**Exposición del modo de búsqueda** (decisión libre del enunciado): vía **configuración** (`RETRIEVAL_SEARCH_MODE`) + **parámetros del pipeline** + **script de evaluación reproducible** (las 4 configuraciones, paso 4). No reescribimos el endpoint `/search` (S8) para no romper su contrato ni sus tests.

## 3. Paso 3 — Integración del reranker (recall-then-rerank)

**Wrapper cross-encoder** (`retrieval/reranker.py`, portado literal): `CrossEncoderReranker` con modelo `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (multilingüe ES+EN, ligero para CPU). **Carga perezosa** con lock (importar el módulo no trae torch; el modelo se carga en el primer `rerank`/`load()`). `rerank(query, candidates, top_n, text_of=…)` reordena por score y corta a `top_n`.

**Patrón recall-then-rerank** en `pipeline.retrieve`: recall amplio (`recall_k=50`) cuando una etapa posterior reordena (fusión o rerank), y corte fino a `rerank_top_n=5`. La inferencia del cross-encoder (síncrona, CPU-bound) se despacha con **`asyncio.to_thread`** para no bloquear el event loop.

**Toggle sin tocar código** (requisito del paso 3): `search_mode`/`rerank` caen a `RETRIEVAL_SEARCH_MODE`/`RERANKER_ENABLED` cuando se pasan `None`, así que se activan/desactivan por **variable de entorno** o por parámetro del pipeline. El reranker se obtiene del *composition root* (`dependencies.get_reranker`, `@lru_cache`, import perezoso).

## 4. Paso 4 — Golden set y medición

**Golden set** (`evals/golden_retrieval.json`): **5 consultas** (descripciones de proyectos a estimar) anotadas a mano con los presupuestos relevantes de nuestro corpus de **15 presupuestos**. Cada consulta incluye **distractores deliberados**: del mismo sector ("similar pero irrelevante", p. ej. *lending* vs *banking*, *monitoring* vs *telemedicine*) y trampas léxicas cross-sector (*mobile wallets* de e-commerce vs una *payments gateway* fintech) — exactamente el modo de fallo que ataca el ejercicio. Un chunk cuenta como relevante si su `budget_id` (en `metadata`) está en `relevant_budget_ids`.

| ID | Consulta (resumen) | Relevantes anotados |
|----|--------------------|---------------------|
| Q1 | Mobile banking, OAuth2, instant payments, ledger | BUD-2024-014, BUD-2024-040 |
| Q2 | Headless e-commerce storefront, catálogo, checkout, recomendaciones | BUD-2024-021, BUD-2024-070, BUD-2023-015 |
| Q3 | Telemedicina, scheduling, video, FHIR | BUD-2024-052, BUD-2023-008, BUD-2023-045 |
| Q4 | Industrial IoT, telemetría, mantenimiento predictivo | BUD-2024-033, BUD-2024-061 |
| Q5 | Payments gateway, fraude, conciliación, ledger | BUD-2024-040, BUD-2024-014 |

**Arnés de medición** (`scripts/eval_retrieval_s10.py`): embebe las consultas una vez (latencia de embedding excluida — es un coste compartido por las 4 configs), calienta el reranker, y ejecuta las **cuatro configuraciones** midiendo **precision@5** (media) y **latencia** (mediana de 3 runs medidos + 1 de calentamiento descartado):

| Config | Búsqueda | Reranking |
|:------:|:--------:|:---------:|
| **A** | Vectorial | No |
| **B** | Híbrida | No |
| **C** | Vectorial | Sí |
| **D** | Híbrida | Sí |

Vive en `scripts/` (herramienta de decisión puntual, no infraestructura de la app). El golden set es un dato versionado.

## 5. Paso 5 — Conclusiones (a cerrar con las cifras reales)

La decisión correcta no la da la técnica sino **la ganancia de relevancia frente a la fracción del presupuesto de latencia** que consume. En nuestro caso de uso (estimación de proyectos, donde la **generación posterior del LLM tarda varios segundos**), unos cientos de ms de reranking son ruido frente a una mejora sustancial del contexto → la hipótesis es que **D (híbrida + reranking)** gana en precisión con un coste de latencia asumible, y que **B** ya aporta sobre **A** en consultas con identificadores exactos (OAuth, FHIR, SCADA, ledger). **El veredicto final se cierra con la tabla A/B/C/D de nuestro corpus** (ver "Cómo ejecutar").

---

## Resumen de cambios por fichero

**Nuevos:**
| Fichero | Qué aporta |
|---------|-----------|
| `alembic/versions/0003_session10_fts.py` | Migración: columna `content_tsv` + índice GIN (paso 1) |
| `app/generation/rag/retrieval/fusion.py` | RRF puro (paso 2) |
| `app/generation/rag/retrieval/reranker.py` | Wrapper cross-encoder, carga perezosa (paso 3) |
| `app/generation/rag/retrieval/pipeline.py` | `retrieve()` recall-then-rerank, 4 configs (pasos 2+3) |
| `app/generation/rag/retrieval/verify_reranker.py` | Pre-flight: descarga/carga/puntúa el modelo |
| `app/generation/rag/retrieval/__init__.py` | Exports del paquete |
| `evals/golden_retrieval.json` | Golden set de 5 consultas anotadas (paso 4) |
| `scripts/eval_retrieval_s10.py` | Arnés de medición A/B/C/D (paso 4) |
| `tests/test_rrf_fusion.py` · `tests/test_reranker.py` · `tests/test_hybrid_retrieve.py` | 16 tests unitarios (RRF puro, reranker con modelo fake, pipeline con store/reranker fakes) |

**Modificados:**
| Fichero | Cambio |
|---------|--------|
| `app/generation/rag/store/models.py` | Columna `content_tsv` (`Computed`, `TSVECTOR`) + índice GIN |
| `app/generation/rag/store/repository.py` | Método `search_lexical` (rama léxica) |
| `app/config.py` | Flags S10: `RETRIEVAL_SEARCH_MODE`, `RERANKER_ENABLED`, `RERANKER_MODEL`, `RETRIEVAL_RECALL_TOP_K`, `RERANK_TOP_N`, `RRF_K` |
| `app/dependencies.py` | `get_reranker()` (singleton, import perezoso) |
| `pyproject.toml` + `uv.lock` | Dependencia `sentence-transformers>=3.0` (arrastra torch) |
| `tests/test_rag_store_models.py` | Introspección del nuevo índice + columna generada |
| `.env.example` | Variables S10 documentadas |

---

## Divergencias respecto a la solución del profesor

> **Actualización — `session_09_live` incorporado.** Las divergencias de *contrato* que tenía esta solución S10 quedaron **RESUELTAS** al portar la Sesión 9 *live*: el pipeline ahora devuelve `RetrievalResult`/`RetrievedChunk` y usa `search_filtered`; existe `RuntimeRetrievalConfig`; la recuperación se expone vía `POST /v1/retrieval/search` (y el flujo `from-transcript` usa híbrida+rerank a través del runtime config). Convergimos al contrato oficial — verificado byte-a-byte en todo el flujo RAG, los routers, RRF, el reranker y la migración FTS.

Divergencias que **permanecen** (preexistentes, de stack/infra, ortogonales a S9/S10):

| Aspecto | Profesor (oficial) | Nuestro repo |
|---------|--------------------|--------------|
| Infra DB | doble Postgres + `halfvec` en search | **Postgres único**, `cosine_distance` simple (sin halfvec) |
| Sesiones conversacionales | (store del brief) | **`DbSessionStore`** en Postgres (divergencia de S5) |
| Frontend | Rails `estimator-web` | **Angular** (proyecto aparte) |
| Meta de `LLMWrapper.complete_structured` | slim (`model`/`provider`/`latency_ms`) | **rica** (tokens, coste, finish_reason) — nuestra telemetría; cambio S9 aplicado de forma aditiva |
| `Sector` | `Literal` cerrado | `str` abierto |
| `tsvector` regconfig | `'english'` | **igual: `'english'`** (mismo dataset, en inglés) |

Lo **idéntico al profesor** (verificado byte-a-byte): todo el flujo RAG (`estimator`, `query_reformulator`, `context_assembler`, `prompt_builder`, `validation`, `observability`, `idempotency`, `retriever`), `retrieval/pipeline.py`, RRF, el reranker, los routers seguros (`retrieval`/`estimate`/`estimate_stages`), `security`/`rate_limiting`/`deps`, la migración FTS, el corpus task-granular y el método de medición (golden set + precision@5 + latencia, 4 configuraciones).

---

## Cómo ejecutar la medición

Requiere: stack levantado (Postgres), corpus ingerido, `OPENAI_API_KEY` en `.env`, y la dependencia instalada (`uv sync` instala torch; primer uso del reranker descarga ~450 MB).

```bash
cd estimator
uv sync                                   # instala sentence-transformers + torch
docker compose up -d                      # Postgres (pgvector/pgvector:pg16) — aplica la migración 0003 en el arranque
uv run python scripts/query_examples.py   # ingiere el corpus base (si no está)

# 1) Pre-flight: ¿descarga, carga y puntúa el cross-encoder?
uv run python -m app.generation.rag.retrieval.verify_reranker

# 2) Medición A/B/C/D (imprime la tabla markdown de precision@5 + latencia)
uv run python scripts/eval_retrieval_s10.py
```

### Resultados (rellenar con la ejecución real sobre nuestro corpus)

| Config | Búsqueda | Reranking | Precision@5 | Latencia (ms) |
|:------:|:--------:|:---------:|:-----------:|:-------------:|
| A | Vectorial | No | _pendiente_ | _pendiente_ |
| B | Híbrida | No | _pendiente_ | _pendiente_ |
| C | Vectorial | Sí | _pendiente_ | _pendiente_ |
| D | Híbrida | Sí | _pendiente_ | _pendiente_ |

> *Patrón esperado* (referencia del material de teoría, no nuestras cifras): el reranking llevó precision@5 de **0,48 → 0,80** a cambio de **35 ms → 290 ms** (+255 ms). En la estimación, +255 ms es <5 % del tiempo total (la generación tarda segundos) → se activa. Nuestras cifras reales deciden el paso 5.

---

## Verificación realizada

- **262 tests pasan** (`uv run pytest`) — 245 de base + 17 nuevos (RRF, reranker, pipeline híbrido, introspección del esquema). Sin regresiones.
- **`ruff check` limpio** en todo el código nuevo/modificado.
- **`uv lock` actualizado** (sentence-transformers v5.6.0 + torch declarados).
- Los tests unitarios **no** requieren torch ni Postgres (el reranker importa torch de forma perezosa; el store se mockea). La **medición A/B/C/D y la verificación del SQL FTS sí requieren el stack vivo** (ver "Cómo ejecutar").
