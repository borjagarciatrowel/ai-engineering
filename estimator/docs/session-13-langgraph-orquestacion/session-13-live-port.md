# Sesión 13 — Port de la sesión en vivo: el grafo se vuelve multi-agente

> Port de `session_13_live` del repo oficial (commit `c20b171`, "session 13 completed") sobre nuestra rama `session-13`.
> Reemplaza el diseño del pre-work ([`session-13-exercise-grafo-langgraph.md`](session-13-exercise-grafo-langgraph.md)): el grafo secuencial de 5 nodos crece hasta un **pipeline de agentes especializados** con dos handovers explícitos (`Command(goto=…)`), dos puertas humanas (`interrupt()` / `Command(resume=…)`) y paralelismo real por tarea (Send API).
> Alcance portado: **solo el servicio IA (FastAPI)**. La parte Rails del oficial (`estimator-web`: wizard de grafo, `Rag::GraphEstimationRun`, vistas de progreso en vivo) se omite — divergencia documentada de siempre: nuestro frontend es Angular y no consume el wizard RAG.

---

## 0. El cambio de forma

El pre-work reexpresó el bucle de la Sesión 12 como cinco nodos **corriendo en fila** (`extract_requirements → classify_components → search_budgets → generate_estimate → validate_and_consolidate`). La sesión en vivo no los hace más rápidos: los **sustituye** por un pipeline distinto, con una forma que el pre-work deliberadamente no necesitaba todavía:

```
START → classifier_agent
classifier_agent      ──Command(goto)──▶  structure_agent        (HANDOVER 1)
structure_agent       ──edge──▶           human_gate_structure   (interrupt #1)
human_gate_structure  ──Send fan-out──▶   estimate_task_hours × N   (paralelo)
estimate_task_hours   ──edge──▶           recover_and_handover   (join)
recover_and_handover  ──Command(goto)──▶  analysis_agent         (HANDOVER 2)
analysis_agent        ──edge──▶           human_gate_analysis    (interrupt #2)
human_gate_analysis   ──conditional──▶    proposal_agent | END
```

`app/domain/graph/nodes.py` (los cinco nodos del pre-work) **se conserva intacto** — ya no está cableado en `build_graph()`, pero queda como el "antes" del que crece este pipeline, tal como lo dejó el propio profesor.

---

## 1. Los ocho nodos (`app/domain/graph/agents/`)

| Agente | Fichero | Qué hace | Reutiliza |
|---|---|---|---|
| `classifier_agent` | `classifier.py` | Transcripción → `complexity` (low/medium/high) + brief reformulado. **Handover 1** a `structure_agent` vía `Command(goto=…, update=…)`. | `LLMWrapper` (gpt-4o-mini) |
| `structure_agent` | `structure.py` | Brief → árbol módulos→tareas. La `complexity` del classifier se mapea a la reasoning effort del agente (`GRAPH_STRUCTURE_EFFORT_BY_COMPLEXITY`). | `run_structure_agent` de S12 (gpt-5), **verbatim** |
| `human_gate_structure` | `gates.py` | **Puerta humana 1**: `interrupt()` expone la estructura propuesta; el resume trae `{"approved": bool, "modules": [...]}` (árbol editado, o vacío para aceptar tal cual). | — |
| `estimate_task_hours` | `hours.py` | **Rama del fan-out**: UNA tarea por invocación (el argumento del `Send`, no el estado completo). Búsqueda vectorial determinista, sin LLM. | `estimate_one` de S10 |
| `recover_and_handover` | `hours.py` | **Join**: lee todo el acumulador `task_hours`, marca las dudosas (sin match / rango contradictorio / `reliability < 0.35`), corre UNA vez el bucle agéntico de recuperación sobre esas, funde resultado, construye la estimación. **Handover 2** a `analysis_agent`. | `run_task_hours_recovery_agent` de S12 (gpt-5), **verbatim** |
| `analysis_agent` | `analysis.py` | Estimación → informe de fiabilidad (`overall_confidence`, `grounded_task_ratio`, `weak_points`). No cambia números, los audita. | `LLMWrapper` (gpt-4o) |
| `human_gate_analysis` | `gates.py` | **Puerta humana 2**: `interrupt()` expone estimación + informe; el resume trae `{"validated": bool, "estimate_overrides": {...}, "want_proposal": bool}`. Si hay overrides con `modules`, **recalcula** los totales (`recompute_estimate_totals`) para que días/ratio/confianza no queden desincronizados de las horas que el humano completó. | `_common.recompute_estimate_totals` |
| `proposal_agent` | `proposal.py` | (Bonus) Estimación validada → propuesta comercial en Markdown. Solo corre si `GRAPH_PROPOSAL_ENABLED` **y** el humano pidió propuesta en la puerta 2. | `LLMWrapper` (gpt-4o) |

Todos los agentes LLM (menos `estimate_task_hours`, que es retrieval puro) aceptan una **persona Matrix** opcional (`personas.py`, activable con `GRAPH_PERSONAS_ENABLED`) — un framing corto antepuesto al system prompt, con una línea de guardarraíl que impide que el personaje sacrifique corrección o forma de salida. Es un toque didáctico del profesor, portado tal cual: no afecta al `response_model` (Pydantic sigue validando la forma).

### 1.1 El estado: de acumulador plano a acumulador con clave

`state.py` gana un tercer acumulador, `task_hours`, pero con un reducer **distinto** de `operator.add`:

```python
def merge_task_hours(existing, new):
    """Keyed by (module, task), last-write-wins — NOT append."""
    by_key = {(t.get("module"), t.get("task")): t for t in (existing or [])}
    for t in new or []:
        by_key[(t.get("module"), t.get("task"))] = t
    return list(by_key.values())
```

Es la corrección directa al gotcha que ya documentamos en el pre-work (reanudar con `operator.add` duplica filas): aquí, si el join reescribe las horas de una tarea recuperada, o si una reanudación re-entra en el fan-out, la clave `(module, task)` **reemplaza**, nunca añade. `test_state.py` lo verifica explícitamente (`test_merge_task_hours_dedupes_by_module_and_task`).

El estado también gana los campos del flujo completo: `complexity`/`reformulated_transcript` (classifier), `structure`/`approved_modules`/`gate1_decision` (structure + puerta 1), `estimate`/`analysis_report`/`gate2_decision` (hours/analysis + puerta 2), `proposal` (bonus).

### 1.2 La disciplina de las puertas: `interrupt()` antes de escribir nada

Ambas puertas en `gates.py` llaman `interrupt()` **como primera línea**, y solo escriben campos de sobrescritura (nunca un acumulador) después. Motivo documentado en el propio módulo: al reanudar, LangGraph **re-ejecuta el nodo entero desde el principio** — cualquier escritura antes del `interrupt()` correría dos veces, y en un reducer acumulador eso duplicaría. Es la misma clase de bug que el reducer con clave soluciona del lado del fan-out; aquí se evita del lado del nodo.

---

## 2. El fan-out real (Send API) — Nivel que el pre-work dejó pendiente

`build.py::fan_out_hours` es la arista condicional que sale de la puerta 1:

```python
def fan_out_hours(state):
    modules = state.get("approved_modules") or []
    sends = [
        Send("estimate_task_hours", {"module": m["name"], "task": t["name"], ...})
        for m in modules for t in (m.get("tasks") or []) if t.get("name")
    ]
    return sends or "recover_and_handover"  # sin tareas, no se estanca
```

Un `Send` por tarea aprobada — todas corren en paralelo de verdad, exactamente el caso que el pre-work medía como "secuencial a propósito, el directo lo paraleliza". El reducer con clave (§1.1) es lo que hace que el join (`recover_and_handover`) reciba el acumulador completo, sin duplicados, sin importar cuántas ramas terminaron ni en qué orden.

---

## 3. El checkpointer: de conexión única a pool

Con dos puertas humanas, una ejecución puede quedar **pausada minutos o días**. `checkpointer.py` cambia de `AsyncPostgresSaver.from_conn_string(...)` (una conexión persistente, que el pre-work usaba) a un `AsyncConnectionPool` de `psycopg_pool`:

```python
pool = AsyncConnectionPool(conninfo=conninfo, min_size=1, max_size=10,
                            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
                            open=False)
await pool.open(wait=True)
checkpointer = AsyncPostgresSaver(pool)
```

Motivo: una conexión única que lleva horas idle puede caer (el servidor, un NAT) — un resume días después chocaría con un socket muerto. El pool valida/reconecta al hacer checkout, así que un resume tardío siempre obtiene una conexión viva. **Sin dependencia nueva**: `psycopg-pool` ya era transitiva (arrastrada por `langgraph-checkpoint-postgres` desde el pre-work), confirmado porque `uv sync` no tuvo que instalar nada adicional para este port.

---

## 4. Los siete endpoints (`app/api/routers/estimate_graph.py`)

El pre-work tenía un único verbo (`POST /v1/estimate/graph`, bloqueante, todo o nada). El directo lo reemplaza por un contrato de **tres verbos bloqueantes** + una **variante en streaming** (para un panel "ver a los agentes trabajar"), todos sobre el mismo `thread_id = estimation_id`:

| Verbo | Qué hace |
|---|---|
| `POST /v1/estimate/graph` | **START**. Corre hasta la primera puerta y devuelve `GraphRunState` (`state="paused"`, `pending_gate` = la estructura a revisar). |
| `POST /v1/estimate/graph/{id}/resume` | **RESUME**. Alimenta `Command(resume=decision)`; sigue a la próxima puerta o a completar. Guarda de idempotencia: reanudar sin nada pendiente → `409`. |
| `GET /v1/estimate/graph/{id}/state` | Lee el snapshot actual (puerta pendiente + artefactos) sin mutar nada — permite recuperar una ejecución pausada tras cualquier retraso. |
| `POST /v1/estimate/graph/stream` | Variante en background: arranca con `graph.astream(..., stream_mode="updates")`, devuelve `202` al instante. |
| `POST /v1/estimate/graph/{id}/resume-stream` | Igual que `resume`, pero en background (`202` inmediato). |
| `GET /v1/estimate/graph/{id}/progress` | Sondea una ejecución en background: `state` (`running`/`paused`/`completed`) + el feed de actividad (`app/domain/graph/activity.py`). |
| `POST /v1/estimate/graph/{id}/proposal` | Genera (o regenera) la propuesta comercial **sin** re-ejecutar el grafo — lee el `estimate` ya persistido en el checkpointer y llama al LLM directo. |

El contrato hacia el backend de negocio sigue siendo HTTP puro y agnóstico de stack — cualquier cliente puede conducir `resume`, no hace falta Rails ni LangChain del otro lado.

### 4.1 El feed de actividad (`activity.py`) — feature del panel en vivo, no de la UI Rails

`GraphActivityLog` es un almacén Redis-o-diccionario (mismo patrón que `app/generation/rag/idempotency.py`) que acumula líneas didácticas ("Complejidad: high", "Backend API: 37 h", …) mientras `graph.astream()` corre en background. `describe_node()` es una función pura (nodo + actualización → líneas) que nunca lanza — un nodo desconocido degrada a una línea genérica. Se porta el backend completo (streaming + feed) aunque no exista un panel Angular que lo consuma todavía: es la misma decisión que ya se tomó en S12 (endpoint sin UI) — la capacidad vive en el servicio IA, lista para cuando (si) el wizard la use.

---

## 5. Qué se portó exactamente

| Fichero | Cambio |
|---|---|
| `app/domain/graph/personas.py` | **nuevo** — personas Matrix por nodo |
| `app/domain/graph/agents/{__init__,_common,classifier,structure,gates,hours,analysis,proposal}.py` | **nuevo** — los 8 agentes + helpers puros |
| `app/domain/graph/activity.py` | **nuevo** — feed de actividad Redis/diccionario |
| `app/domain/graph/state.py` | **reescrito** — nuevos campos de flujo + reducer con clave `merge_task_hours` |
| `app/domain/graph/schemas.py` | **ampliado** — `ComplexityClassification`/`ReliabilityReport`/`WeakPoint`/`CommercialProposal` |
| `app/domain/graph/build.py` | **reescrito** — grafo multi-agente, `fan_out_hours`, `route_after_gate2` |
| `app/domain/graph/checkpointer.py` | **reescrito** — `AsyncConnectionPool` en vez de conexión única |
| `app/domain/schemas/graph_estimation.py` | **ampliado** — `GraphResumeRequest`/`GraphRunState`/`PendingGate`/`GraphProgress`/`ActivityEntry`/`GraphProposalResponse` |
| `app/api/routers/estimate_graph.py` | **reescrito** — los 7 verbos |
| `app/config.py` | + `GRAPH_CLASSIFIER_MODEL`/`GRAPH_ANALYSIS_MODEL`/`GRAPH_PROPOSAL_MODEL`/`GRAPH_PROPOSAL_ENABLED`/`GRAPH_PERSONAS_ENABLED`/`GRAPH_STRUCTURE_EFFORT_BY_COMPLEXITY` |
| `app/dependencies.py` | + `get_graph_activity()` |
| `scripts/run_graph_s13.py` | **reescrito** — corre el pipeline completo auto-aprobando ambas puertas |
| `tests/domain/graph/{test_state,test_graph}.py` | **reescritos** para el grafo multi-agente |
| `tests/domain/graph/{test_activity,test_estimate_recompute,test_personas_proposal}.py` | **nuevos** |

`pyproject.toml`/`uv.lock`: **sin cambios** — `psycopg-pool` ya era transitiva desde el pre-work (verificado: `uv sync` no instaló nada nuevo para este port).

### 5.1 Divergencias respecto al oficial

| Aspecto | Oficial `session_13_live` | Nuestro repo |
|---|---|---|
| Servicio IA (FastAPI) | commit `c20b171` | **idéntico** — los puntos de integración (`run_structure_agent`/`run_task_hours_recovery_agent` con soporte `persona` ya presente desde nuestro port de S12 live, `estimate_one`, `distance_weighted_consensus`, `AgentTaskRef`) ya convergían byte a byte |
| Rails: wizard de grafo (`Agents::GraphFlow`, `Rag::GraphEstimationRun`, controladores/vistas de progreso) | sí | **omitido** — nuestro frontend es Angular y no consume el wizard RAG (mismo criterio que todos los ports live anteriores) |
| Panel "ver a los agentes trabajar" | alimentado por el wizard Rails | backend (`activity.py` + endpoints `/stream`/`/progress`) **portado y verificado**, sin UI que lo consuma aún |
| Transcripción de la sesión en vivo (`demo_ciclo_completo.txt`, plataforma energética NÓVA) | sí, nueva | **no copiada** — se reutilizó la transcripción compleja ya portada en `exercises/session-12/` (RUTA, logística) para la ejecución real, evitando un fichero de fixture redundante |
| Traza-entregable | run del profesor | **nuestra** run real: transcripción compleja de S12, corpus real de 60 proyectos, Postgres real, ambas puertas auto-aprobadas |

---

## 6. Verificación (ejecución real)

### 6.1 Tests

```
$ uv run pytest tests/domain/graph -v
30 passed
$ uv run pytest -q
470 passed
```

447 tests previos (pre-work S13 incluido) + 23 nuevos netos: el `test_graph.py` del pre-work (3 tests sobre el grafo secuencial) se **reemplazó** por 7 tests sobre el multi-agente (handovers, ambas puertas, fan-out sin duplicar, recuperación agéntica disparada por una tarea marcada, override de gate 2 recalculando totales), y se añadieron `test_activity.py` (7), `test_estimate_recompute.py` (5), `test_personas_proposal.py` (4) + 3 tests nuevos de `test_state.py` sobre el reducer con clave.

### 6.2 Smoke offline (`--memory --stub`, todo real salvo las horas por tarea)

```
$ uv run python scripts/run_graph_s13.py --memory --stub --estimation-id s13-live-smoke
  ⏸ human gate 'structure_review' → auto-resume {'approved': True}
  ⏸ human gate 'final_review' → auto-resume {'validated': True, 'want_proposal': True}
...
TOTAL: 502d (4016.0h, confidence high)
RELIABILITY REPORT: overall_confidence=high, grounded_task_ratio=1.0
COMMERCIAL PROPOSAL (proposal_agent — bonus): [propuesta completa generada]
```

Classifier, structure (gpt-5, real), analysis y proposal corrieron contra la API real; solo `estimate_task_hours` usó el stub determinista (horas sintéticas por hash de tarea, sin BD), así que ninguna tarea quedó marcada y el bucle de recuperación gpt-5 no se disparó — comportamiento esperado del stub.

### 6.3 Ejecución real de punta a punta (Postgres + retrieval real + corpus de 60 proyectos)

```
$ uv run python scripts/run_graph_s13.py \
    --out exercises/session-13/example_run_complex.txt --estimation-id s13-live-real

estimation_id : s13-live-real
complexity    : high
status        : validated
...
TOTAL: 87d (695.0h, confidence medium)
RELIABILITY REPORT: overall_confidence=low, grounded_task_ratio=0.256
```

Sin recorte de ningún tipo: sobre la transcripción compleja de S12 (logística, ~90 tareas), el corpus real de 60 proyectos/1543 tareas solo fundamentó el 25.6 % — incluso después de que `recover_and_handover` corriera el bucle agéntico de recuperación sobre las marcadas. Es un resultado honesto, no un fallo: un corpus histórico pequeño para un dominio muy amplio ("threat modeling", "backups y DR", "gestión de secretos"…) no tiene análogos para todo, y el informe de fiabilidad lo dice explícitamente en su `summary` — exactamente la señal que la puerta humana 2 existe para capturar. Traza completa (estructura, 87 tareas, informe de fiabilidad y propuesta comercial) en [`exercises/session-13/example_run_complex.txt`](../../exercises/session-13/example_run_complex.txt).

Verificado en Postgres: el checkpointer persistió 10 checkpoints (uno por transición de nodo, incluidas las dos pausas) bajo `thread_id=s13-live-real`, conviviendo con las tablas de pgvector, sin infraestructura nueva.

### 6.4 El flujo HTTP completo, con las dos puertas reales

```
$ curl -X POST .../v1/estimate/graph -d '{"transcript": "...", "estimation_id": "s13-http-live-smoke"}'
→ 200 {"state": "paused", "pending_gate": {"gate": "structure_review", ...}}

$ curl -X POST .../v1/estimate/graph/s13-http-live-smoke/resume -d '{"decision": {"approved": true}}'
→ 200 {"state": "paused", "pending_gate": {"gate": "final_review", "payload": {"estimate": {...}, "analysis_report": {...}}}}

$ curl -X POST .../v1/estimate/graph/s13-http-live-smoke/resume \
    -d '{"decision": {"validated": true, "want_proposal": true}}'
→ 200 {"state": "completed", "status": "validated", "estimate": {"total_engineer_days": 63, ...}, "proposal": "..."}

# Guarda de idempotencia:
$ curl -X POST .../v1/estimate/graph/s13-http-live-smoke/resume -d '{"decision": {}}'
→ 409 {"detail": "No pending human gate for this estimation_id (already completed or unknown)."}

$ curl .../v1/estimate/graph/s13-http-live-smoke/state
→ 200 {"state": "completed", "status": "validated", ...}
```

El contrato de tres verbos (`start` → `resume` × 2 → `state`) funciona real, contra un servidor levantado en el puerto 8010 (el 8000 estaba ocupado por otro proyecto local) con el checkpointer real sobre Postgres — no simulado con `MemorySaver`.

---

## 7. Cómo ejecutar

```bash
cd estimator

# Stack mínimo (Postgres con pgvector + Redis; el checkpointer crea sus tablas solo)
docker compose up -d postgres redis
uv run alembic upgrade head

# Smoke offline (todo real salvo las horas por tarea — sin BD)
uv run python scripts/run_graph_s13.py --memory --stub

# Ejecución real (retrieval de verdad, corpus ya ingerido en el pre-work)
uv run python scripts/run_graph_s13.py \
    --out exercises/session-13/example_run_complex.txt

# Vía HTTP (start → resume × 2)
uv run uvicorn app.main:app --port 8010 &
curl -X POST http://localhost:8010/v1/estimate/graph -H "X-API-Key: $ESTIMATE_API_KEY" \
    -d '{"transcript": "...", "estimation_id": "..."}'
curl -X POST http://localhost:8010/v1/estimate/graph/{id}/resume -H "X-API-Key: $ESTIMATE_API_KEY" \
    -d '{"decision": {"approved": true}}'
curl -X POST http://localhost:8010/v1/estimate/graph/{id}/resume -H "X-API-Key: $ESTIMATE_API_KEY" \
    -d '{"decision": {"validated": true, "want_proposal": true}}'

# Tests (sin red)
uv run pytest tests/domain/graph -v
```
