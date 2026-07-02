# Sesión 11 — Ejercicio resuelto: citación verificable a nivel de línea + baseline RAGAS

> Resolución del ejercicio previo a la Sesión 11 ("RAG avanzado: generación y calidad 🔴").
> Resuelto **igual que el profesor** (rama oficial `session_11`, commit `3292744` — "solved pre exercise session 11"), **adaptado a las divergencias de nuestro repo**.
> Alcance del enunciado: **Parte 1** (citación verificable a nivel de línea de estimación) + **Parte 2** (evaluación RAGAS básica sobre el golden set extendido con `ground_truth`). NO incluye síntesis multi-fuente ni detección de alucinaciones más allá de la integridad referencial — eso se construye en la sesión en vivo.

---

## 0. Punto de partida y estrategia

A diferencia de la Sesión 10 (donde tuvimos que portar el *delta* sobre una base S8 propia porque nunca habíamos portado la S9 *live*), en la Sesión 11 partimos de un flujo de generación **ya convergido byte-a-byte con el oficial** tras el port de `session_09_live`/`session_10_live` (ver [`estimator-session10-live-port`](../../../../.claude/projects/-Users-borjagarciacueto-Documents-Claude-Projects-ai-engineering/memory/estimator-session10-live-port.md)). Eso significa que el diff del profesor entre `session_10` y `session_11` (`3292744`) se aplica **casi literal** sobre nuestros ficheros: `schemas.py`, `context_assembler.py`, `prompt_builder.py`, `validation.py`, `estimator.py` y `estimate_stages.py` eran, antes de este ejercicio, idénticos a la base oficial pre-S11.

Decisión: **portar el diff oficial línea a línea**, adaptando solo lo que depende de datos reales del corpus (el golden set de generación) y de un bug preexistente que bloqueaba cualquier medición fiable (ver §0.1).

### 0.1 Bug encontrado y corregido antes de poder medir nada: `evals/golden_retrieval.json` corrupto

Antes de poder extender el golden set de la Sesión 10 con `ground_truth` (paso 2.1 del enunciado), verificamos que sus anotaciones fueran correctas contra nuestro corpus real. **No lo eran.** El commit `f53df4c` ("S10-live StageConfig harness + multi-collection golden set") sobrescribió las 5 consultas Q1–Q5 originales (correctamente anotadas contra `data/budgets_sample.json` en el commit `304743b`, "session 10 pre-work") con los ids del repositorio **oficial** (`BUD-2024-001`, `BUD-2024-003`, `BUD-2024-005`…), que **no existen** en nuestro corpus — el nuestro usa un esquema de ids distinto y no secuencial (`BUD-2024-014`, `BUD-2024-021`, `BUD-2024-033`…) sembrado desde la Sesión 7. El contenido de los 15 presupuestos es el mismo (mismo `project_summary`, mismos componentes y horas) — solo los `budget_id` difieren.

Consecuencia: desde `f53df4c`, cualquier `precision@k` calculada sobre Q1–Q5 con `scripts/eval_retrieval_s10.py` era **matemáticamente cero o sin sentido** (ningún chunk recuperado podía tener un `budget_id` que apareciera en `relevant_budget_ids`), de forma completamente silenciosa — exactamente el "fallo que no da error" de la Parte 5 de la teoría de la Sesión 11 (deriva de índice/anotación), pero aquí en la capa de golden set, no del índice vectorial.

**Corrección**: re-anotamos Q1–Q8 leyendo el contenido real de `data/budgets_sample.json` + `data/transcripts_sample.json` + `data/technical_docs_sample.json`, verificando cada id contra el corpus. Q8 ya era correcto (no referencia ningún `budget_id`). El detalle completo queda documentado dentro del propio `evals/golden_retrieval.json` (campo `description`). Re-ejecutar `scripts/eval_retrieval_s10.py` tras la corrección devuelve números sanos (Q1–Q5 con precision@5 entre 0,72 y 1,00 según configuración — ver §5), confirmando la corrección.

Sin este arreglo, el `ground_truth` de la Parte 2 se habría construido sobre presupuestos que la recuperación real nunca podría encontrar, y el baseline RAGAS habría medido ruido.

---

## 1. Parte 1 — Citación verificable a nivel de línea

### 1.1 Schema extendido (`app/generation/rag/schemas.py`)

- **`SourceReference{chunk_id, document_id, evidence}`** — la citación verificable de una línea: `chunk_id` es el `id` del `<source>` recuperado, `document_id` el presupuesto histórico del que viene, `evidence` un fragmento o cifra **verbatim** (no parafraseado).
- **`TaskItem`** (cada línea de estimación) pasa de `sources: list[int]` a `grounded: bool` + `sources: list[SourceReference]`. Un `@model_validator(mode="after")` impone la regla de integridad del enunciado: `grounded=True` ⇒ ≥1 fuente; `grounded=False` ⇒ sin fuentes **y** sin `engineer_days` inventados (`None`). La violación lanza `ValidationError`, así que Instructor puede re-preguntar al modelo en vez de dejar pasar una línea inconsistente.
- **`CitationReport`/`LineCitation`** — la salida de `verify_citations`: por línea (`module`, `component`, `status ∈ {grounded, dangling, insufficient}`, `cited_chunk_ids`, `dangling_chunk_ids`) y en agregado (`total_lines`, `grounded_lines`, `dangling_lines`, `insufficient_lines`, `verified_citations`, `dangling_citations`, con la propiedad `has_dangling`).
- **`GenerateResult`** gana `citation_report: CitationReport | None` (junto al `fabricated_source_ids: list[str]` ya existente, ahora derivado de `citation_report.dangling_citations` en vez de calculado aparte).

### 1.2 Ensamblado de contexto (`context_assembler.py`)

Cada `<source>` XML expone ahora también `document_id` (tomado de `chunk.source_id or chunk.budget_id`), para que el modelo pueda copiar el presupuesto histórico concreto en cada cita, no solo el id de chunk.

### 1.3 Atribución obligatoria por línea (`prompt_builder.py`)

Las reglas del prompt de generación (tanto la ruta con horas como la ruta de estructura sin horas, Sesión 10) cambian de "cita el id de la fuente en `sources`" a: por cada tarea con soporte histórico, `grounded=true` + `sources` con `chunk_id`/`document_id`/`evidence` **verbatim**; sin soporte, `grounded=false`, `sources` vacío, `engineer_days` nulo — nunca estimar a ojo. El ensamblado de estructura sin recuperación (`build_structure_user_message`) no se toca: nunca tiene `<source>`, así que la contract por defecto (`grounded=False`, `sources=[]`) ya es correcta ahí.

### 1.4 Verificación post-generación (`validation.py::verify_citations`)

Reemplaza `validate_citations` (que solo devolvía una lista plana de ids fabricados). Recorre cada línea (`modules[].tasks[]`) **y** las citaciones globales heredadas de la Sesión 9 (`estimate.sources`), y para cada `chunk_id` citado comprueba pertenencia al conjunto de chunks realmente recuperados (`retrieved_chunk_ids: set[str]`). Clasifica cada línea en `grounded` / `dangling` (cita un id que nunca estuvo en el contexto — la alucinación con apariencia de rigor) / `insufficient` (marcada `grounded=False`, sin inventar). `verify_citations_for_chunks` es un wrapper de conveniencia que deriva el set desde una lista de `RetrievedChunk`.

Se integra en dos sitios:
- **`estimator.py`** (flujo completo `estimate_from_transcript`): tras generar, calcula el `CitationReport`, lo loguea con `structlog` (`citation_report`, correlacionado por `request_id`), y si `has_dangling` reintenta una vez con feedback explícito citando los ids colgantes; si persisten, degrada `confidence="low"` y loguea `citations_unrepaired`.
- **`estimate_stages.py`** (endpoint `/v1/estimate/stages/generate`, la maqueta paso-a-paso): no reintenta (deja el fallo visible como "momento de enseñanza"), pero devuelve `citation_report` completo + `fabricated_source_ids` en el cuerpo de la respuesta. El contrato HTTP no cambia de forma — solo se enriquece.

### 1.5 Demo offline de aceptación (`scripts/demo_verify_citations_s11.py`)

Sin red ni base de datos: construye 3 chunks "recuperados" (dos de `BUD-2024-014`, uno de `BUD-2024-040`) y una `Estimate` con 4 líneas — dos correctamente fundamentadas, **una con una citación colgante plantada a propósito** (`chunk_id="999"`, nunca recuperado) y una **sin datos suficientes** (`grounded=False`). Ejecuta `verify_citations` y comprueba programáticamente los tres criterios de aceptación del enunciado. Salida real en §5.

---

## 2. Parte 2 — Evaluación RAGAS básica

### 2.1 Golden set extendido (`evals/golden_generation_s11.json`)

Parte de las 5 consultas Q1–Q5 del golden set de recuperación **ya corregido** (§0.1). Para cada una se añaden dos campos nuevos:
- `transcript`: notas de reunión (100–300 palabras) que alimentan el pipeline real (`reformulate_query` → `retrieve` → `generate_estimate`), en vez de pasar la `query` corta directamente.
- `ground_truth`: la estimación de referencia en **engineer-days** (horas del componente ÷ 8), derivada leyendo los componentes reales de `data/budgets_sample.json` — nunca inventada. Cada cifra del `ground_truth` es trazable a un `component_id`/horas real del corpus.

Dos consultas se diseñaron deliberadamente como casos límite del contrato de la Parte 1, no solo como preguntas de recuperación:
- **Q3** (telemedicina) combina **dos presupuestos que no se solapan**: `BUD-2024-052` cubre vídeo/e-prescripción/facturación pero no tiene *scheduling* ni FHIR; `BUD-2023-008` cubre *scheduling*/FHIR/historia clínica pero no vídeo. Ningún presupuesto solo responde a la consulta — es el caso de síntesis multi-fuente más claro del set.
- **Q5** (pasarela de pagos) pide **detección de fraude**, que **no existe en ningún presupuesto del corpus** (ni `BUD-2024-040` ni `BUD-2024-014` ni ningún otro). El `ground_truth` lo señala explícitamente: un sistema correcto debe dejar esa línea `grounded=false`, no estimarla a ojo. Es un stress test deliberado del contrato de fundamentación — confirmado en producción real, ver §5.

### 2.2 Arnés de evaluación (`scripts/eval_ragas_s11.py` + `scripts/score_ragas_s11.py`)

`eval_ragas_s11.py` ejecuta el pipeline real (`reformulate_query` → embed → `retrieve` híbrido+rerank → `truncate_to_token_budget` → `build_context_block` → `generate_estimate` → `verify_citations`) por cada consulta del golden set, y registra las cuatro entradas que RAGAS necesita (`question`, `answer` — la estimación renderizada a texto plano —, `contexts` — el contenido de los chunks retenidos —, `ground_truth`). Después calcula `faithfulness`, `answer_relevancy`, `context_precision`, `context_recall` con `gpt-4o-mini` como juez y `text-embedding-3-small` para las métricas basadas en embeddings.

**Nota operativa (misma que el profesor, verificada en nuestro stack):** `ragas==0.4.3` importa en carga `langchain_community.chat_models.vertexai`, módulo que nuestro `langchain-community` (0.4.2) no expone — falla con `ModuleNotFoundError` al primer `from ragas import evaluate`. Como el juez es siempre OpenAI (nunca Vertex), `score_ragas_s11.py::_install_vertex_shims()` registra un módulo *stub* con una clase `_Unavailable` (que lanza si alguien la instancia) antes de importar `ragas`, y `eval_ragas_s11.py::run_ragas` lo invoca automáticamente. A diferencia del profesor (que necesitó un venv aislado porque su stack de `langchain` era más nuevo y el conflicto era irreconciliable), en nuestro repo el *shim* basta para correr colección y puntuación **en el mismo venv** — `--collect-only`/`--score-file` quedan como vía de escape si una futura subida de `langchain` rompe la coexistencia.

### 2.3 Tabla de métricas

Ver resultados reales en §5 y en [`session-11-exercise-citacion-verificable-ragas_results.md`](session-11-exercise-citacion-verificable-ragas_results.md).

---

## 3. Resumen de cambios por fichero

**Nuevos:**
| Fichero | Qué aporta |
|---------|-----------|
| `scripts/demo_verify_citations_s11.py` | Demo offline de `verify_citations` con cita colgante plantada (paso 1.5, prueba de aceptación) |
| `scripts/eval_ragas_s11.py` | Arnés de colección + evaluación RAGAS end-to-end sobre el pipeline real (paso 2.2) |
| `scripts/score_ragas_s11.py` | Puntuador RAGAS independiente (colección/puntuación desacopladas; shim de Vertex) |
| `evals/golden_generation_s11.json` | Golden set de generación: Q1-Q5 + `transcript` + `ground_truth` reales (paso 2.1) |
| `evals/ragas_baseline_s11.json` | Salida real de la ejecución: 4 métricas × 5 consultas + `citation_report` por consulta |
| `tests/generation/rag/test_validation.py` (reescrito) | 10 tests: `verify_citations` (grounded/dangling/insufficient/global/vacío/wrapper) + 3 de integridad del schema (`_grounding_integrity`) |

**Modificados:**
| Fichero | Cambio |
|---------|--------|
| `app/generation/rag/schemas.py` | `SourceReference`, `TaskItem.grounded`/`sources: list[SourceReference]` + validador, `CitationReport`/`LineCitation`, `GenerateResult.citation_report` |
| `app/generation/rag/context_assembler.py` | `document_id` en el `<source>` XML |
| `app/generation/rag/prompt_builder.py` | Atribución por línea obligatoria (`grounded`/`chunk_id`/`document_id`/`evidence`) en ambas rutas de generación |
| `app/generation/rag/validation.py` | `validate_citations` → `verify_citations` (+ `verify_citations_for_chunks`) |
| `app/generation/rag/estimator.py` | Reintento correctivo sobre `report.has_dangling`, logging `citation_report`/`citations_unrepaired` |
| `app/api/routers/estimate_stages.py` | `/v1/estimate/stages/generate` devuelve `citation_report` |
| `evals/golden_retrieval.json` | **Corrección de bug**: Q1-Q8 re-anotados contra el corpus real (§0.1) |
| `pyproject.toml` + `uv.lock` | `ragas>=0.2`, `datasets>=2.19` (dev); `langchain-openai` ya estaba en dependencias principales |
| `tests/generation/rag/test_estimator.py`, `tests/api/test_estimate_stages.py` | Adaptados al nuevo contrato `TaskItem`/`SourceReference`/`CitationReport` |

---

## 4. Divergencias respecto a la solución del profesor

Ninguna de contrato: `schemas.py`, `context_assembler.py`, `prompt_builder.py`, `validation.py`, `estimator.py` y `estimate_stages.py` quedan **idénticos byte-a-byte** al diff oficial `3292744`, salvo:

| Aspecto | Profesor (oficial) | Nuestro repo | Motivo |
|---------|--------------------|--------------|--------|
| Golden set de partida | `BUD-2024-001..017` (ids propios, correctos desde el inicio) | `BUD-2024-014`/`021`/`033`… (ids propios desde S7) | Los dos corpus tienen 15 presupuestos con el mismo contenido semántico pero ids distintos — no es un error, es una divergencia de datos preexistente. El **error real** era que nuestro `golden_retrieval.json` había sido sobrescrito con los ids del profesor por accidente (§0.1), no que los ids en sí difieran. |
| `ground_truth` del golden set de generación | Ficticio: cita `component_id` inventados no presentes literalmente en el JSON de datos (p. ej. `PSD2-002`) | Real: cada `component_id`/hora citado en `ground_truth` existe literalmente en `data/budgets_sample.json` | Preferimos que el `ground_truth` sea 100% verificable contra el corpus, no solo plausible. |
| Modelo juez / embeddings | `gpt-4o-mini` / `text-embedding-3-small` | Igual | — |
| Import de Vertex en `ragas` | Requiere venv aislado (`langchain-community` más nuevo, conflicto irreconciliable) | Resuelto con un *shim* en el mismo venv (`langchain-community==0.4.2`) | Nuestra versión de `langchain-community`, aunque no expone `vertexai`, no tiene el conflicto de dependencias más profundo que forzó al profesor a aislar el venv. |

---

## 5. Verificación realizada

- **378 tests pasan** (`uv run pytest`) — 368 de base (tras la Sesión 10-live) + 10 nuevos/reescritos en `test_validation.py` (netos, sustituyendo los 4 tests de `validate_citations`). Sin regresiones en `test_estimator.py`/`test_estimate_stages.py` (adaptados al nuevo contrato).
- **`ruff check` limpio** en todo el código nuevo/modificado.
- **Demo offline de citación** (`uv run python scripts/demo_verify_citations_s11.py`): `ACCEPTANCE: PASS` — 2 líneas `grounded` con fuente real, 1 `dangling` (id `999` plantado, detectado), 1 `insufficient` (sin horas inventadas). Ver tabla completa en el doc de resultados.
- **Golden set de recuperación corregido**, re-verificado ejecutando `scripts/eval_retrieval_s10.py` sobre el stack real: Q1-Q5 vuelven a dar precision@5 sana (0,60–1,00 según consulta y configuración) en vez del 0 silencioso que producía el bug de §0.1.
- **Baseline RAGAS real** (`scripts/eval_ragas_s11.py`, stack levantado + corpus de 15 presupuestos/60 chunks ingerido + `OPENAI_API_KEY`): 4 métricas × 5 consultas + promedio, más el `citation_report` de cada una de las 5 estimaciones reales generadas (171 líneas en total, **0 citas colgantes**). Tabla completa y hallazgos en [`session-11-exercise-citacion-verificable-ragas_results.md`](session-11-exercise-citacion-verificable-ragas_results.md).

---

## Cómo ejecutar

Requiere: stack levantado (Postgres), corpus base ingerido, `OPENAI_API_KEY` en `.env`, dependencias de evaluación instaladas.

```bash
cd estimator
uv sync --group dev                         # instala ragas + datasets (langchain-openai ya estaba)
docker compose up -d                        # Postgres (pgvector/pgvector:pg16)
uv run python scripts/query_examples.py     # ingiere el corpus base (15 presupuestos / 60 chunks) si no está

# 1) Demo offline de citación verificable (sin red, sin DB)
uv run python scripts/demo_verify_citations_s11.py

# 2) Baseline RAGAS real (llama al pipeline real + OpenAI; usa GENERATION_MODEL=gpt-5
#    con reasoning_effort=high — sube LLM_TIMEOUT por encima del default de 30s)
DATABASE_URL='postgresql+asyncpg://postgres:postgres@localhost:5432/estimator' \
LLM_TIMEOUT=180 \
  uv run python scripts/eval_ragas_s11.py --out evals/ragas_baseline_s11.json
```
