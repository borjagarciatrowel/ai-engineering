# Sesión 12 — Port de la sesión en vivo: el agente entra en el wizard

> Port de `session_12_live` del repo oficial (commit `4489a73`, "session 12 completed") sobre nuestra rama `session-12`.
> Reemplaza el diseño del pre-work ([`session-12-exercise-agente-a-mano.md`](session-12-exercise-agente-a-mano.md)): el agente deja de ser **un disparo autónomo al lado del pipeline** y pasa a **conducir las dos fases del wizard** que ya existían, alrededor de la puerta de revisión humana.
> Alcance portado: **solo el servicio IA (FastAPI)**. La parte Rails del oficial (perfiles de agente con avatar, vistas de traza) se omite — divergencia documentada: nuestro frontend es Angular y no consume el wizard RAG.

---

## 0. El cambio de idea

El pre-work construyó `run_estimation_agent`: un bucle que leía una transcripción y producía una estimación completa **por su cuenta**, en paralelo al pipeline fijo. La sesión en vivo lo tira y lo reencuadra:

> El agente no sustituye al pipeline ni corre a su lado: **conduce las mismas dos fases que el wizard ya tenía**, y en la segunda solo actúa donde el camino determinista ha fallado.

Eso convierte al agente de "otra forma de hacer lo mismo" en "una capa de decisión donde de verdad hace falta", que es exactamente la tesis de la Parte 1 de la teoría (*por defecto el pipeline; el agente cuando no te quede otra*).

**Consecuencia directa:** `run_estimation_agent` desaparece. En su lugar hay dos entradas:

| Fase | Función | Tools | Qué decide |
|---|---|---|---|
| **1 — structure** | `run_structure_agent` | **ninguna** (`STRUCTURE_TOOL_SCHEMAS = []`) | Descompone el brief en módulos→tareas. Sin horas, sin recuperación. |
| **2 — hours recovery** | `run_task_hours_recovery_agent` | `search_budgets`, `derive_task_hours`, `validate_estimate` | Solo sobre las tareas que el pase determinista **no pudo fundamentar**. |

---

## 1. Lo híbrido es el punto

`agent_estimate_task_hours` (el conductor) no le da la fase 2 entera al agente:

1. Corre **primero** el consenso determinista de S10 (`estimate_all`) sobre **todas** las tareas.
2. Marca las que fallaron, con su razón (`_flag_reason`): sin analog histórico bajo el umbral, analogs que se contradicen (`hours_range` en vez de punto), o `reliability < 0.35`.
3. Si no hay ninguna marcada → **el agente no se invoca**. Coste extra cero en el camino feliz, y devuelve una traza de 0 pasos para que la UI pueda decir "no hizo falta recuperación".
4. Si las hay, el agente re-busca **solo esas**, y se hace *merge* de lo que recupere sobre el resultado determinista (pisando `estimated_hours`/`reliability`/`has_match` y tirando el `hours_range` obsoleto).

Es el **enrutado** de la Parte 5/6 de la teoría aplicado dentro de una fase: pagas la autonomía únicamente donde el camino barato se quedó corto.

### 1.1 El agente decide la búsqueda, nunca la aritmética

La tool `calculate_estimate` del pre-work (mediana + 15 % de contingencia, inventada para el ejercicio) **se elimina**. La sustituye `derive_task_hours`, que recibe los vecinos que el agente encontró y calcula las horas con **la misma función de consenso ponderado por distancia que usa el camino determinista** — expuesta ahora como alias público en `task_hours.py`:

```python
# Public alias for the consensus primitive. Session 12: the agentic hours-recovery
# loop injects this as its ``consensus_fn`` (via the conductor) so the agent's
# ``derive_task_hours`` tool reuses the SAME distance-weighted math as the
# deterministic path — the agent decides the search, never the arithmetic.
distance_weighted_consensus = _consensus
```

Por eso la fase 2 **no tiene `responses.parse` terminal**: las horas recuperadas salen de las *salidas de las tools*, no de un número que el modelo escriba. La no-determinación se queda en *qué se busca*; el número es determinista y reproducible.

---

## 2. Arquitectura: dónde vive cada pieza (y por qué)

El bucle necesita retrieval (territorio de `rag`), pero `generation/agentic` y `generation/rag` son **hermanos** y `ARCHITECTURE.md` prohíbe que se importen entre sí. La solución del oficial, portada tal cual:

| Pieza | Ubicación | Razón |
|---|---|---|
| `AgentTrace` / `AgentStep` | `app/domain/schemas/agent_trace.py` | Contrato de auditoría **compartido**: `agentic` lo *produce*, pero `GenerateResult`/`TaskHoursResult` (de `rag`) lo *transportan*. Ambos hermanos pueden importar `domain/schemas`, así que aparcarlo ahí deja que `rag` lo embeba sin importar `agentic`. |
| `make_retrieval_backend` | `app/generation/rag/agent_retrieval.py` | **Envuelve `retrieve()`** → es territorio de `rag`. El bucle solo conoce un tipo *estructural* `Callable[[str, list[str] | None], Awaitable[list[dict]]]` y recibe el closure **inyectado**. El backend toma `(query, sectors)` planos, no el `SearchBudgetsArgs` de `agentic`, justo para no acoplar. |
| `agent_propose_structure` / `agent_estimate_task_hours` | `app/domain/agent_estimation.py` | El conductor: **el único sitio donde `agentic` y `rag` se encuentran** (ARCHITECTURE §7). Recibe el cliente async inyectado por el router; nunca toca el composition root. |
| Router | `app/api/routers/estimate_agent.py` | Transporte fino. |

Esto obligó a mover el `AgentTrace` que el pre-work tenía dentro de `agent_schemas.py`, y a sacar el backend de retrieval de `agent_tools.py` (donde el pre-work lo tenía importando `rag` directamente — un import cruzado que la sesión en vivo corrige).

---

## 3. Los dos endpoints

```
POST /v1/estimate/agent/structure   → GenerateResult  (+ agent_trace)
POST /v1/estimate/agent/hours       → TaskHoursResult (+ agent_trace)
```

- **Mismos modelos de respuesta** que sus gemelos deterministas (`/stages/structure`, `/tasks/hours`), solo enriquecidos con `agent_trace`. El wizard los parsea sin cambios.
- Auth con el mismo `ESTIMATE_API_KEY`, rate limit `15/minute`, fallos de bucle/LLM → 502, cliente async ausente → 500 (misconfiguración).
- **Los endpoints deterministas siguen intactos** — son la comparación en vivo y, además, la base del híbrido.
- Los request models nuevos (`AgentStructureRequest`/`AgentHoursRequest`) añaden *knobs por run* que caen a los settings `AGENT_*` cuando son `null`: `model`, `reasoning_effort`, `max_iterations`, `search_top_k`, `search_distance_threshold` y `persona` (instrucciones extra que se anexan al system prompt — lo que en el oficial alimenta los "perfiles de agente" de la UI Rails).

---

## 4. Qué se portó exactamente

| Fichero | Cambio |
|---|---|
| `app/domain/schemas/agent_trace.py` | **nuevo** — `AgentStep`/`AgentTrace` + `render()` STEP N |
| `app/domain/agent_estimation.py` | **nuevo** — el conductor (fase 1 + fase 2 híbrida con flag/merge) |
| `app/generation/rag/agent_retrieval.py` | **nuevo** — `make_retrieval_backend` / `default_retrieval_backend` |
| `app/api/routers/estimate_agent.py` | **nuevo** — los dos endpoints |
| `app/generation/agentic/agent_loop.py` | **reescrito** — `run_structure_agent` + `run_task_hours_recovery_agent` |
| `app/generation/agentic/agent_schemas.py` | **reescrito** — `AgentStructure`/`AgentTaskRef`/`AgentTaskDerivation`/`AgentTaskHoursRun`; el trace se va a `domain` |
| `app/generation/agentic/agent_tools.py` | **reescrito** — `derive_task_hours` sustituye a `calculate_estimate`; backend inyectado |
| `app/generation/rag/task_hours.py` | alias público `distance_weighted_consensus` |
| `app/generation/rag/schemas.py` | `agent_trace` en `GenerateResult`/`TaskHoursResult` + `AgentStructureRequest`/`AgentHoursRequest` |
| `app/main.py` | registra `estimate_agent_router` |
| `scripts/run_agent_s12.py` | **reescrito** — corre las dos fases (auto-aprobando la estructura) |
| `exercises/session-12/sample_transcript_meridiano.txt` | **nuevo** — transcripción del directo |
| tests | `tests/domain/test_agent_estimation.py`, `tests/api/test_estimate_agent.py`, `tests/generation/rag/test_agent_retrieval.py` (nuevos) + reescritos los de `agentic/` |

`config.py` y `dependencies.py` **no cambian** — las 5 vars `AGENT_*` y `get_async_openai_client()` del pre-work siguen valiendo.

### 4.1 Divergencias respecto al oficial

| Aspecto | Oficial `session_12_live` | Nuestro repo |
|---|---|---|
| Servicio IA (FastAPI) | commit `4489a73` | **idéntico**, salvo los 2 ficheros que ya divergían (`main.py`: router `records` + creación de tablas al arrancar; `rag/schemas.py`: docstring/`Sector` propios) — el delta S12 se aplicó a mano ahí |
| Rails: perfiles de agente (`agents/profiles`), avatar (Active Storage), vistas de traza, seeds, migraciones | sí | **omitido** — nuestro frontend es Angular y no consume el wizard RAG (los ports live de S9–S11 ya lo omitieron) |
| `persona` en los requests | la rellena el perfil de agente de la UI | soportado en la API; sin UI que lo alimente |
| Traza-entregable | run de `gpt-5` + retrieval real | **nuestra** run de `gpt-5-mini`/`medium` + `--stub` (reproducible sin DB) |

---

## 5. Verificación

**Suite completa: 440 tests verdes** (420 antes del port → +20: conductor, router, backend de retrieval y los reescritos del bucle). `ruff check` limpio. La app arranca y registra las dos rutas:

```
$ uv run python -c "from app.main import app; print([r.path for r in app.routes if 'agent' in r.path])"
['/v1/estimate/agent/structure', '/v1/estimate/agent/hours']
```

**Ejecución real de las dos fases** (`gpt-5-mini`, `--effort medium`, `--stub`, transcripción compleja):

```
agent_structure_done        confidence=medium modules=10 tasks=68
agent_hours_recovery_start  flagged=68 model=gpt-5-mini
agent_hours_recovery_done   derived=56 iterations=4 steps=125 stopped_reason=completed
```

Fase 1 descompone en 10 módulos / 68 tareas; la fase 2 ejercita el bucle (125 pasos reason→act→observe en 4 vueltas) y funda 56 de las 68. Traza en [`exercises/session-12/example_trace_complex.txt`](../../exercises/session-12/example_trace_complex.txt), regenerada con el flujo nuevo.

> **Nota de calibración observada:** con `--effort low` la fase 2 **no llama a ninguna tool** (`no tool steps`) y no funda nada. No es un bug del port — es el dial de razonamiento de la Parte 6 de la teoría enseñando los dientes: bajar el esfuerzo abarata la llamada y compra un agente que decide no actuar. Para la traza-entregable hay que usar `medium`.
