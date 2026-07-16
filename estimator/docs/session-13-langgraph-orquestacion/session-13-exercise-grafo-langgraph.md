# Sesión 13 — Ejercicio resuelto: el flujo de estimación como grafo de LangGraph

> Resolución del ejercicio previo a la Sesión 13 ("Orquestación de agentes 🔴").
> Resuelto **igual que el profesor** (rama oficial `session_13`, commit `4c23c2e` — "solved pre exercise session 13"), **adaptado a las divergencias de nuestro repo**.
> Alcance del enunciado: reexpresar el bucle agéntico de la Sesión 12 como un **grafo explícito de LangGraph** (5 nodos, estado tipado con reducers, checkpointer sobre Postgres, observabilidad con Logfire), corriendo **en secuencial** — sin paralelismo, sin manejo de errores avanzado y sin intervención humana (`interrupt()`), que llegan en el directo. Niveles 1 y 2 obligatorios; Nivel 3 (primera arista condicional) opcional — **los tres implementados**.

---

## 0. Punto de partida y estrategia

Como en la Sesión 12, partimos de un servicio IA ya convergido con el oficial (S9-S12 live). Eso significa que las piezas de las que depende el grafo — `LLMWrapper.complete_structured` (`app/foundation/llm/wrapper.py`), `make_retrieval_backend` (`app/generation/rag/agent_retrieval.py`, ya escrito en S12 sobre `chunk_type='historical_task'`), `DATABASE_URL` con el driver `postgresql+psycopg://`, `AVAILABLE_MODELS` con `gpt-4o`/`gpt-4o-mini` — son **idénticas** a la base oficial. El diff del profesor se aplicó **fichero a fichero, casi literal**: ni un solo punto de integración tuvo que adaptarse.

Decisión: **portar el diff oficial completo** (Niveles 1, 2 y 3 — el enunciado marca el 3 como opcional pero el profesor lo resolvió, así que nosotros también), sin reimplementar nada del pipeline de recuperación o generación — el grafo solo **envuelve** en nodos lo que ya existía en `app/generation/rag/` y `app/foundation/llm/`.

### 0.1 Dónde vive el grafo, y por qué no es un hermano de `generation`

El grafo compone `generation/rag` (retrieval) + `foundation/llm` (generación) — exactamente lo que la Sesión 12 ya hacía desde su bucle a mano. Por la misma regla arquitectónica que mantiene `agent_loop.py` fuera de `generation/agentic/` como compositor, el grafo vive en `app/domain/graph/`, **junto a `estimation_service.py`**: es otro conductor, no un hermano de `generation`. `ARCHITECTURE.md` §4 se actualizó con un párrafo dedicado (ver §6 más abajo).

---

## 1. Qué se construyó

Nueve piezas de código + el kit del ejercicio, todo dentro del servicio IA:

| Fichero | Rol |
|---|---|
| `app/domain/graph/state.py` | El **estado tipado** (`TypedDict`) con dos reducers acumuladores (`budget_matches`, `errors`) vía `Annotated[..., operator.add]`. |
| `app/domain/graph/schemas.py` | Los modelos Pydantic **internos** de cada nodo LLM (`RequirementsExtraction`, `ComponentClassification`, `ConsolidatedEstimate`) — separados del contrato público. |
| `app/domain/graph/nodes.py` | Los **cinco nodos** como funciones puras (`state → actualización parcial`), cada uno envuelto en `logfire.span("node: …")`. |
| `app/domain/graph/build.py` | `build_graph(checkpointer)` — cablea y compila el grafo (Nivel 1) con la arista condicional del Nivel 3. |
| `app/domain/graph/checkpointer.py` | El **checkpointer** `AsyncPostgresSaver` sobre el Postgres del proyecto (deriva el DSN plano de `DATABASE_URL`). |
| `app/domain/graph/observability.py` | Configuración de **Logfire** (un span por nodo; no-op sin token). |
| `app/domain/schemas/graph_estimation.py` | El contrato HTTP público (`GraphEstimateRequest`/`Response`) — no cambia de cara al backend de negocio. |
| `app/api/routers/estimate_graph.py` | `POST /v1/estimate/graph` — el endpoint (mismo contrato de siempre: transcripción in, estimación + `status` out). |
| `scripts/run_graph_s13.py` | Script ejecutable que produce el entregable (traza de una ejecución completa). |
| `app/main.py` + `app/config.py` + `.env.example` | Construcción del grafo en el `lifespan` (con checkpointer), `configure_logfire(app)`, router incluido, 3 vars `GRAPH_*`/`LOGFIRE_*` nuevas. |
| `tests/domain/graph/` | 7 tests sin red (reducers + grafo end-to-end con dobles). |

---

## 2. El estado tipado y sus reducers (`state.py`) — Nivel 1.1

```python
class EstimationState(TypedDict, total=False):
    transcript: str
    estimation_id: str
    requirements: list[str]
    components: list[Component]
    budget_matches: Annotated[list[BudgetMatch], operator.add]   # acumulador
    estimate: Optional[dict]
    status: Optional[str]                                        # "validated" | "needs_review"
    errors: Annotated[list[str], operator.add]                   # acumulador
```

Dos campos acumuladores (el enunciado pide al menos uno): `budget_matches` porque `search_budgets` busca componente a componente y cada iteración solo debe **añadir**, nunca reemplazar, lo que ya se encontró; `errors` porque cualquier nodo puede anotar un fallo blando sin taparse con el de otro. El resto de campos (`status`, `estimate`, `requirements`, `components`) son de sobrescritura por defecto — el último valor manda, que es justo lo que quieres para un resultado terminal.

`total=False` es necesario porque el `ainvoke` inicial solo aporta `transcript` + `estimation_id`; cada nodo va rellenando el resto.

---

## 3. Los cinco nodos (`nodes.py`) — Nivel 1.2

```
START → extract_requirements → classify_components → search_budgets
      → generate_estimate → validate_and_consolidate → (condicional, Nivel 3) → END
```

- **`extract_requirements`** — transcripción → lista de requisitos. LLM estructurado (`GRAPH_EXTRACTION_MODEL=gpt-4o-mini`) vía `LLMWrapper.complete_structured`.
- **`classify_components`** — requisitos → componentes con categoría. Mismo modelo barato.
- **`search_budgets`** — para cada componente, recupera presupuestos de referencia **uno tras otro** (bucle `for`, sin `asyncio.gather` — eso lo trae el directo con la Send API). Reutiliza `make_retrieval_backend()` sobre `chunk_type='historical_task'`, el mismo retrieval real de S9/S10 que ya usaba el agente de S12. Un fallo de recuperación por componente es **blando**: se anota en `errors` y el bucle continúa con los demás.
- **`generate_estimate`** — consolida componentes + `budget_matches` en una estimación estructurada (`GRAPH_GENERATION_MODEL=gpt-4o` — el modelo barato deja `engineer_days` en `null` con demasiada frecuencia al convertir horas→días y sacar la mediana, así que la consolidación numérica se queda con el modelo más caro).
- **`validate_and_consolidate`** — guardrails deterministas (rango plausible `[min·0.5, max·2]` en días respecto a las referencias, total que cuadra con la suma de componentes) portados literalmente de `agent_tools.validate_estimate` (S12), y fija el `status` de salida.

Cada nodo recibe el estado completo y devuelve **solo** el trozo que cambia — son funciones puras, triviales de testear con dobles (§7).

---

## 4. Persistencia y observabilidad — Nivel 2

### 4.1 Checkpointer (`checkpointer.py`)

`AsyncPostgresSaver` sobre el **mismo** `DATABASE_URL` que ya usa el proyecto (el que tiene pgvector). Su DSN tiene que ser libpq plano (`postgresql://…`), no la forma SQLAlchemy (`postgresql+psycopg://…`) que usa el resto del servicio — `saver_conninfo()` hace ese strip, reflejando exactamente lo que `_async_database_url()` ya hacía en `app/foundation/persistence/database.py` para el driver `asyncpg` (Sesión 8). `checkpointer.setup()` es idempotente: crea sus tres tablas (`checkpoints`, `checkpoint_writes`, `checkpoint_blobs`) en el primer arranque y no hace nada en los siguientes.

El grafo se construye en el `lifespan` de `main.py`, con el checkpointer abierto dentro de un `AsyncExitStack` que vive tanto como la app. Si Postgres no está disponible al arrancar, `app.state.graph` queda en `None` y el endpoint responde `503` **sin tumbar el resto del servicio** — el mismo patrón defensivo que ya usan `create_all()` y `get_catalog()` en el `lifespan`.

**Verificación real** — las tablas del checkpointer conviven con las de pgvector en el mismo Postgres:

```
$ docker compose exec postgres psql -U postgres -d estimator -c "\dt"
 public | budget_chunks          | table
 public | checkpoint_blobs       | table   ← nuevas, S13
 public | checkpoint_migrations  | table   ← nuevas, S13
 public | checkpoint_writes      | table   ← nuevas, S13
 public | checkpoints            | table   ← nuevas, S13
 public | documents              | table
 ...

$ docker compose exec postgres psql -U postgres -d estimator \
    -c "SELECT thread_id, count(*) FROM checkpoints GROUP BY thread_id;"
           thread_id           | count
--------------------------------+-------
 s13-http-smoke                |     7
 s13-sample_transcript_complex |     7
```

Sin infraestructura nueva: `docker compose up -d postgres redis` + una migración de Alembic ya presente (`0005_session11_hnsw_multi_index`) fue suficiente — el checkpointer crea sus propias tablas al vuelo.

### 4.2 Observabilidad con Logfire (`observability.py`)

`configure_logfire(app)` se llama una vez al definir la `app` de FastAPI (no dentro del `lifespan`, para que la instrumentación de FastAPI se registre antes del primer request):

- `logfire.instrument_fastapi(app)` da el span raíz por petición.
- `logfire.instrument_httpx()` captura las llamadas salientes a OpenAI (embeddings + LLM), porque el SDK de OpenAI corre sobre `httpx`.
- Cada nodo envuelve su cuerpo en `with logfire.span("node: <nombre>")` → **un span por nodo** dentro de la traza de la petición.

`send_to_logfire="if-token-present"`: sin `LOGFIRE_TOKEN` en el entorno, los spans se ejecutan igual (localmente) pero no se exportan — la observabilidad nunca puede tumbar el arranque del servicio ni bloquear un run sin credenciales de Logfire.

**Verificación real** (log de una ejecución real vía `scripts/run_graph_s13.py`, un span por nodo visible en el log estructurado que corre en paralelo a los de Logfire):

```
graph_checkpointer_ready
llm_structured_call_started    model=gpt-4o-mini response_model=RequirementsExtraction
llm_structured_call_completed  ... latency_ms=2918 ...
graph_node_extract_requirements requirements=5
llm_structured_call_started    model=gpt-4o-mini response_model=ComponentClassification
graph_node_classify_components components=4
rag_retrieve_done              collection=budget results=5 search_mode=vector   ← × 4 (una por componente)
graph_node_search_budgets      components=4 errors=0 matches=20
llm_structured_call_started    model=gpt-4o response_model=ConsolidatedEstimate
graph_node_generate_estimate   components=4 confidence=medium total_engineer_days=18
graph_node_validate            issues=0 status=validated
```

Con `LOGFIRE_TOKEN` en el entorno, la misma ejecución exporta la traza completa (con los spans HTTP anidados de cada llamada al modelo) a Pydantic Logfire — no configurado en esta run local, documentado tal cual (el enunciado permite optar por LangSmith documentando cuál se usó; nosotros usamos Logfire, que es la opción que mejor encaja con el stack full-stack FastAPI + asyncpg + Postgres, como explica la teoría de la Parte 6).

---

## 5. La primera arista condicional — Nivel 3 (opcional, implementado)

```python
def route_on_status(state: EstimationState) -> str:
    return "needs_review" if state.get("status") == "needs_review" else "validated"

builder.add_conditional_edges(
    "validate_and_consolidate",
    route_on_status,
    {"validated": END, "needs_review": END},
)
```

Sustituye la arista fija `validate_and_consolidate → END` por una función de enrutado que lee el `status` que el propio nodo de validación acaba de fijar. Ahora mismo ambas ramas terminan en `END` — el reintento serio, el fallback y la intervención humana con `interrupt()` se montan en el directo, tal como marca el enunciado —, pero la bifurcación ya es explícita y real: la ejecución real contra el endpoint HTTP (§7) la disparó de forma natural, sin forzar nada.

---

## 6. Divergencias respecto al oficial

| Aspecto | Oficial `session_13` | Nuestro repo |
|---|---|---|
| Código del grafo (`state`/`schemas`/`nodes`/`build`/`checkpointer`/`observability`) | commit `4c23c2e` | **idéntico** — los puntos de integración (`LLMWrapper`, `make_retrieval_backend`, `DATABASE_URL`) ya estaban convergidos desde S8-S12 |
| Contrato HTTP (`graph_estimation.py` + `estimate_graph.py`) | idéntico | **idéntico** |
| `main.py` (lifespan + router + Logfire) | idéntico | **idéntico** |
| Kit del ejercicio | `exercises/session-13/{README,sample_transcript_complex.txt,example_run_complex.txt}` | **transcripción reutilizada, no duplicada**: `sample_transcript_complex.txt` es byte-a-byte igual al de `exercises/session-12/` (ya lo confirmó el propio diff oficial), así que `run_graph_s13.py` apunta ahí en vez de copiarlo — evita un fichero redundante. `example_run_complex.txt` sí se generó de nuevo, con nuestra propia ejecución real. |
| Traza-entregable | run del profesor (modelo/corpus propios) | **nuestra** run real: `gpt-4o-mini` (extract/classify) + `gpt-4o` (generate), corpus de 60 proyectos / 1543 tareas ingerido con `scripts/build_task_corpus.py --ingest`, retrieval real (no stub) |
| `CLAUDE.md` con design point S13 | sí | nuestro repo **no mantiene** `CLAUDE.md` (divergencia ya documentada en S12) — el design point vive en este doc y en la memoria |
| `ARCHITECTURE.md` | párrafo "el grafo también es conductor" en §4 | **idéntico** (portado, adaptado a nuestro árbol de ficheros) |
| Doc de sesión en `docs/` | no (el oficial usa solo `exercises/.../README.md`) | **sí** — este fichero, por la convención `session-NN-exercise-*` del resto de nuestras sesiones |

---

## 7. Verificación (ejecución real)

Se levantó el stack (`docker compose up -d postgres redis`), se aplicó la migración pendiente (`uv run alembic upgrade head`), se ingirió el corpus de tareas real (`uv run python scripts/build_task_corpus.py --ingest` contra un servidor host en el puerto 8010 — el 8000 estaba ocupado por otro proyecto local) y se corrió el grafo **de verdad**, sin stub, dos veces:

### 7.1 Vía el script (checkpointer real + retrieval real)

```
$ uv run python scripts/run_graph_s13.py --out exercises/session-13/example_run_complex.txt

checkpointer  : AsyncPostgresSaver
retrieval     : real retrieve()
estimation_id : s13-sample_transcript_complex

graph_node_extract_requirements requirements=5
graph_node_classify_components components=4
rag_retrieve_done  × 4 (una búsqueda vectorial real por componente, candidates_evaluated=1543)
graph_node_search_budgets      components=4 errors=0 matches=20
graph_node_generate_estimate   components=4 confidence=medium total_engineer_days=18
graph_node_validate            issues=0 status=validated

status : validated
TOTAL: 18d (confidence medium)
```

Traza completa (requisitos, componentes, los 20 `budget_matches` con su `reference_budget_id` y `distance` reales, la estimación por componente y el total) en [`exercises/session-13/example_run_complex.txt`](../../exercises/session-13/example_run_complex.txt) — **el entregable**.

### 7.2 Vía el endpoint HTTP (contrato de siempre) — y el Nivel 3 en acción

```
$ curl -X POST http://localhost:8010/v1/estimate/graph -H "X-API-Key: ..." \
    -d '{"transcript": "...", "estimation_id": "s13-http-smoke"}'

{
  "status": "needs_review",
  "estimate": { "components": [...6 componentes...], "total_engineer_days": 18, ... },
  "errors": [
    "'Rate limiting service' has no historical reference (unbudgeted).",
    "'Caching and Queue management' has no historical reference (unbudgeted)."
  ]
}
```

Sobre una transcripción distinta (la simple de S12: OAuth2 + JWT + multi-tenant + rate limiting + Redis), dos de los seis componentes no encontraron referencia histórica → el guardrail los marca `unbudgeted` → `validate_and_consolidate` fija `status="needs_review"` → la arista condicional del **Nivel 3** enruta de verdad, sin forzar el caso a mano.

### 7.3 Un hallazgo real que confirma la teoría (Parte 3, reducers al reanudar)

Al primer intento, un fallo al escribir el fichero de salida hizo que el script se reejecutara **con el mismo `estimation_id`** (y por tanto el mismo `thread_id`). El resultado: `budget_matches` apareció con **45 entradas en vez de 20**, con nombres de componente inconsistentes entre sí — exactamente el gotcha que describe [la teoría de la Sesión 13, Parte 3](session-13-theory-langgraph-orquestacion.md): *"al reanudar una ejecución desde un checkpoint, si pasas un estado inicial que incluye campos acumuladores, el reducer no reemplaza — combina"*. Se limpiaron los checkpoints de ese `thread_id` (`DELETE FROM checkpoints/checkpoint_writes/checkpoint_blobs WHERE thread_id = ...`) y se repitió la ejecución con un `thread_id` limpio para la traza-entregable. Queda anotado aquí porque es la prueba más concreta de por qué el artículo insiste en no reutilizar `thread_id` entre ejecuciones que deberían ser independientes.

### 7.4 Tests sin red

```
$ uv run pytest tests/domain/graph -v
tests/domain/graph/test_graph.py::test_graph_runs_end_to_end_and_accumulates_budget_matches PASSED
tests/domain/graph/test_graph.py::test_validation_failure_routes_to_needs_review PASSED
tests/domain/graph/test_graph.py::test_route_on_status_maps_status_to_branch PASSED
tests/domain/graph/test_state.py::test_accumulator_fields_are_annotated_with_operator_add PASSED
tests/domain/graph/test_state.py::test_accumulator_fields_compile_to_a_reducer_channel PASSED
tests/domain/graph/test_state.py::test_reducer_concatenates_partial_updates PASSED
tests/domain/graph/test_state.py::test_errors_reducer_appends_without_clobbering PASSED
======================== 7 passed ========================
```

`test_graph.py` corre el grafo completo con `MemorySaver` + un `LLMWrapper` falso (scripted por `response_model`) + un backend de retrieval falso — cero red, cero clave de API — y cubre tanto el camino `validated` como el `needs_review` (Nivel 3). `test_state.py` verifica los reducers a nivel de canal compilado de LangGraph (no solo la anotación de tipos).

Suite completa del repo: **447 tests verdes** (440 previos de S12 + 7 nuevos de S13).

---

## 8. Cómo ejecutar

```bash
cd estimator

# Stack mínimo (Postgres con pgvector + Redis; el checkpointer crea sus tablas solo)
docker compose up -d postgres redis
uv run alembic upgrade head

# Depuración offline con el stub (sin corpus real para search_budgets)
uv run python scripts/run_graph_s13.py --memory --stub

# Ejecución real (retrieval de verdad): ingerir el corpus de tareas contra un servidor arriba,
# luego correr el grafo con el checkpointer de Postgres
uv run uvicorn app.main:app --port 8010 &
ESTIMATOR_BASE_URL=http://localhost:8010 uv run python scripts/build_task_corpus.py --ingest
uv run python scripts/run_graph_s13.py --out exercises/session-13/example_run_complex.txt

# Vía HTTP (mismo contrato de siempre)
curl -X POST http://localhost:8010/v1/estimate/graph -H "X-API-Key: $ESTIMATE_API_KEY" \
    -d '{"transcript": "...", "estimation_id": "..."}'

# Tests (sin red)
uv run pytest tests/domain/graph -v
```

`--memory` usa un `MemorySaver` en memoria en vez del checkpointer de Postgres. `--stub` cambia el retrieval real por el stub offline ya portado en S12 (`exercises/session-12/reference_retrieval.py`).
