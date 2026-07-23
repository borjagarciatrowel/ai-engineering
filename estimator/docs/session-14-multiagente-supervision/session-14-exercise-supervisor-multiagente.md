# Sesión 14 — Ejercicio resuelto: supervisor, mínimo privilegio e intervención humana

> Resolución del ejercicio previo a la Sesión 14 ("Sistemas multi-agente y patrones avanzados 🔴").
> Resuelto **igual que el profesor** (rama oficial `session_14`, commit `d5830a0` — "exercise solved", diffeado contra `c20b171` = `session_13_live`), **adaptado a las divergencias de nuestro repo**.
> Alcance del enunciado: convertir el flujo de estimación en una topología **supervisor / workers** donde el modelo decide en runtime quién actúa (Nivel 1, obligatorio), añadir una **pausa humana disparada por señal** sobre el checkpointer de la S13 (Nivel 2, obligatorio) y **validar + auditar** cada acción de agente (Nivel 3, ampliación). **Los tres implementados.**
> Marco teórico: [`session-14-theory-multiagente-supervision.md`](session-14-theory-multiagente-supervision.md).

---

## 0. Punto de partida y estrategia

Partimos del port completo de `session_13_live` (grafo multi-agente con handovers explícitos, dos puertas humanas y fan-out por Send API). Eso significa que **todo lo que este ejercicio necesita ya existía**: el estado tipado con reducers, el `AsyncPostgresSaver` sobre el Postgres del proyecto, las tres tools de la S12, los prompts y guardarraíles deterministas de `graph/nodes.py`, y Logfire cableado en cada nodo.

La frontera que cruza esta sesión no es infraestructura, es **quién es dueño del control flow**. En la S13 el orden lo escribía `build.py` en tiempo de escritura; aquí lo elige un modelo en cada vuelta. Por eso el diff del profesor **no toca nada de lo anterior**: añade un paquete paralelo.

Decisión: **portar el diff oficial completo**, fichero a fichero. Los diez puntos de integración que el paquete necesita (`_EXTRACT_SYSTEM_PROMPT`, `_CLASSIFY_SYSTEM_PROMPT`, `_GENERATE_SYSTEM_PROMPT`, `_validate`, `_references_for`, `_norm`, `HOURS_PER_DAY`, `_max_tokens_for`, `_reasoning_effort_for` en `nodes.py`; `dispatch_tool`/`RetrievalBackend`/`ConsensusFn` en `agent_tools.py`; `make_retrieval_backend`; `distance_weighted_consensus`) son **idénticos** a los oficiales, así que no hubo que adaptar ni una firma. 64 tests nuevos pasaron a la primera.

### 0.1 Por qué un paquete nuevo y no una rama del grafo existente

El flujo S13-live (`classifier → structure → gate1 → fan-out → recover → analysis → gate2 → proposal`) y sus siete endpoints quedan **intactos**. El supervisor vive en `app/domain/graph/supervisor/` como un **segundo grafo** que comparte el mismo checkpointer.

Dos consecuencias que merecen nombrarse:

- **Un solo `AsyncPostgresSaver`, un solo juego de tablas `checkpoints`.** Sin más, el mismo `estimation_id` enviado a `/graph` y a `/supervisor` intercalaría dos estados incompatibles en un mismo hilo — y LangGraph intentaría alegremente reanudar un estado de S14 dentro de la topología de S13. Por eso el router namespacea: `thread_id = "s14:<estimation_id>"`.
- **Se construyen por separado en el `lifespan`.** El checkpointer se abre una vez; después cada grafo se compila en su propio `try`, así que si uno falla el otro sigue en pie (`app.state.graph` / `app.state.supervisor_graph`, cada uno con su 503).

---

## 1. Qué se construyó

| Fichero | Rol |
|---|---|
| `app/domain/graph/supervisor/state.py` | `SupervisorState`, que **hereda** de `EstimationState` (S13) + los dos acumuladores *keyed* nuevos: `agent_contributions` (auditoría) y `routing_history` (enrutado). |
| `app/domain/graph/supervisor/privilege.py` | La tabla `AGENT_PRIVILEGES`, `PrivilegeViolation` y `guarded_dispatch` (comprobar → ejecutar → auditar). **Nivel 3**. |
| `app/domain/graph/supervisor/agents.py` | Los cuatro especialistas como funciones puras, reutilizando prompts, `response_model`s y guardarraíles de `graph/nodes.py`. |
| `app/domain/graph/supervisor/supervisor.py` | El enrutador a mano: digest del estado, `SupervisorDecision` tipada, `Command(goto=…)` y los tres frenos. **Nivel 1**. |
| `app/domain/graph/supervisor/gate.py` | `review_reasons` (las tres condiciones, función pura) + `human_review_gate` (`interrupt()`). **Nivel 2**. |
| `app/domain/graph/supervisor/build.py` | `build_supervisor_graph(checkpointer)` — la estrella, con `destinations=` declarado explícitamente. |
| `app/domain/graph/schemas.py` | +`SupervisorTarget` (el `Literal` de destinos) y `SupervisorDecision`. |
| `app/domain/schemas/supervisor_estimation.py` | El contrato HTTP (request, resume tipado, `PendingHumanReview`, `SupervisorRunState`). |
| `app/api/routers/estimate_supervisor.py` | Los tres verbos: START / resume / state. |
| `scripts/run_supervisor_s14.py` | Ejecuta el flujo e imprime enrutado + privilegio + auditoría + revisión. |
| `app/main.py` + `app/config.py` + `.env.example` | Ambos grafos sobre un checkpointer compartido, router incluido, 6 vars `SUPERVISOR_*` nuevas. |
| `tests/domain/graph/supervisor/` + `tests/api/test_estimate_supervisor.py` | **64 tests** sin red (estado, enrutado, privilegio, puerta, grafo end-to-end, ciclo HTTP). |
| `exercises/session-14/` | README del ejercicio, dos transcripciones (edge case / happy path) y la traza comprometida. |

---

## 2. El estado: heredado, no redeclarado (Nivel 1.2)

```python
class SupervisorState(EstimationState, total=False):
    next_agent: Optional[str]
    route_reason: Optional[str]
    supervisor_steps: int                                        # SIN reducer, a propósito
    routing_history: Annotated[list[RoutingRecord], append_routing]
    agent_contributions: Annotated[list[AgentContribution], append_contributions]
    ...
```

El enunciado pide "estado tipado **extendido** desde el de la S13, con al menos un reducer acumulador". La lectura literal es la herencia: `TypedDict` hace que LangGraph pliegue los reducers del padre en el juego de canales del hijo, así que `budget_matches` y `errors` llegan ya correctos, junto con las formas `Component`/`BudgetMatch`.

El coste, dicho claro: los canales del S13 *live* (`structure`, `task_hours`, `gate1_decision`…) vienen de regalo y aparecen vacíos en `snapshot.values`. Son `total=False` y ningún nodo de S14 los escribe, así que el coste es un canal sin usar cada uno — más barato que duplicar seis definiciones de campo y dos anotaciones de reducer, e invisible por HTTP porque el `response_model` del router proyecta solo lo que le interesa.

**Los dos acumuladores nuevos usan un reducer *keyed*, no `operator.add`** — por la misma razón que `merge_task_hours` en la S13: `interrupt()` **reejecuta el nodo entero** al reanudar, así que una lista concatenada crecería una fila duplicada en cada pausa humana. Al indexar por identidad, una fila reemitida **reemplaza** en lugar de añadirse.

Dos detalles que fijan bugs reales:

- **La clave de auditoría incluye el `args_digest`** (SHA-256 corto de los argumentos canónicos), no solo `(step, agent, action)`. Un agente llama legítimamente a su tool **una vez por componente**: sin los argumentos en la clave, la segunda búsqueda **sustituiría** a la primera y la auditoría perdería filas en silencio. Cubierto por `test_repeated_tool_calls_in_one_step_are_kept_apart`.
- **`supervisor_steps` NO lleva reducer.** Tiene exactamente un escritor (el supervisor) y es de sobrescritura: un contador acumulador rompería el presupuesto de pasos al reanudar. Cubierto por `test_step_counter_has_no_reducer`.

---

## 3. El supervisor a mano (Nivel 1.1)

### 3.1 Qué ve para decidir: el digest

```python
def _summarise(state) -> str:
    ...
    return "\n".join([
        "Estimation state so far:",
        f"- transcript: {len(state.get('transcript') or '')} characters",
        f"- requirements: {len(state.get('requirements') or [])} extracted",
        f"- components: {len(components)} classified ({component_names})",
        f"- budget_matches: {len(matches)} references covering {grounded}/{len(components)} components",
        f"- estimate: {'produced' if estimate else 'not produced yet'}",
        f"- validation: {'run' if state.get('validation') else 'not run yet'}",
        f"- agents already dispatched: {', '.join(done) or 'none'}",
        "", "Which agent must act next?",
    ])
```

Deliberadamente **no** es la transcripción cruda ni un historial de mensajes. El enrutador necesita saber **qué existe**, no qué dice. Coste constante por decisión, independientemente de lo larga que sea la transcripción o de cuántas vueltas lleve el flujo.

### 3.2 La decisión es un tipo cerrado

```python
SupervisorTarget = Literal[
    "requirements_extractor", "budget_searcher",
    "estimate_generator", "coherence_validator", "finish",
]

class SupervisorDecision(BaseModel):
    next_agent: SupervisorTarget
    reason: str          # nadie lo lee en runtime; se lee en la traza
    confidence: Confidence = "medium"
```

El modelo no puede inventarse un destino, solo elegir entre los cinco que el grafo conoce. `LLMWrapper.complete_structured` **no expone `temperature`** y añadirlo tocaría `foundation`, de la que dependen todas las sesiones — así que el presupuesto de determinismo se gasta en el esquema constreñido, la guarda de legalidad y un digest corto y factual.

### 3.3 Los tres frenos

| Freno | Qué impide | Dónde |
|---|---|---|
| **Presupuesto de pasos** (`SUPERVISOR_MAX_STEPS=8`) | Aristas de vuelta cíclicas + router LLM = ping-pong infinito. Techo duro sobre bucles **y** sobre gasto. | Primera comprobación del nodo; fuerza `goto="human_review_gate"` con `source="limit"`. |
| **Guarda de legalidad** (`_is_legal`) | Un destino cuyas entradas no existen todavía, y re-visitas de un agente que ya actuó. | Tras la respuesta del modelo; si la propuesta es ilegal, cae a la escalera y lo registra como `source="fallback"`. |
| **Fallback determinista** (`_fallback_next`) | Que una caída del LLM cuelgue el grafo. | Excepción del router → escalera de dependencias. Es también lo que permite que los tests **no toquen la red**. |

Un detalle que merece leerse, porque fija un bug real: `_already_ran` mira el **historial de enrutado**, no si el canal de salida del agente está poblado. La diferencia carga peso: una búsqueda de presupuestos que legítimamente **no encuentra nada** deja `budget_matches` vacío, y una comprobación basada en la salida leería eso como "aún no lo ha hecho" y volvería a enrutar al mismo agente **para siempre**. *"¿Actuó?"* es la pregunta honesta; *"¿produjo?"* es otra, y la contesta el validador. Cubierto por `test_an_empty_search_result_does_not_loop_the_router`.

Cada decisión se escribe en `routing_history` con su razón y su `source` (`llm` / `fallback` / `limit`). Sin ese campo, una traza no puede distinguir un modelo que enrutó bien de un modelo al que corrigieron en cada paso.

---

## 4. Los cuatro agentes y el mínimo privilegio (Niveles 1 y 3)

| Agente | Tools que puede usar | Qué produce |
|---|---|---|
| `supervisor` | **ninguna**: solo enruta | la decisión |
| `requirements_extractor` | **ninguna** (solo el modelo) | `requirements` + `components` (dos llamadas estructuradas) |
| `budget_searcher` | `search_budgets` | `budget_matches` |
| `estimate_generator` | `derive_task_hours` | `component_anchors` + `estimate` |
| `coherence_validator` | `validate_estimate` | `validation`, `confidence`, `out_of_range`, `grounded_components` |

> **Nota sobre nombres.** El enunciado llama `calculate_estimate` a la tool de cálculo. En este repo se llama **`derive_task_hours`** (consenso ponderado por distancia sobre los análogos, sin LLM); `calculate_estimate` solo existe como esqueleto del alumno en `exercises/session-12/`. Misma función, otro nombre. No se crean tools nuevas: **se reparten** las de la S12.

Esto no es solo higiene de seguridad. Como dice la teoría, la tasa de elección incorrecta de tool sube con el número de opciones: aquí **cada agente ve como mucho UNA tool**, así que no hay nada que equivocar. La propiedad de seguridad y la de precisión salen del mismo reparto.

Y es **exigible, no documentación**:

```python
async def guarded_dispatch(agent, tool, args, *, step, ...):
    allowed = allowed_tools(agent)
    if tool not in allowed:                      # la comprobación, ANTES de ejecutar
        log.error("agent_privilege_denied", ...)
        contribution = {..., "outcome": "denied", ...}
        if settings.SUPERVISOR_PRIVILEGE_STRICT:
            raise violation
        return {"ok": False, "error": "privilege_denied", ...}, contribution
    result = await dispatch_tool(tool, args, ...)   # solo se llega aquí si está permitido
```

Tres decisiones de diseño que importan:

- **`dispatch_tool` no llega a llamarse** en una denegación. Es exactamente lo que verifica `test_denied_call_never_reaches_dispatch`, envolviendo el dispatcher real con un espía.
- **La contribución se *devuelve*, no se escribe.** Así los agentes siguen siendo funciones puras `state → actualización parcial`: la traza se pliega en el estado por el valor de retorno y pasa por el reducer como cualquier otro canal.
- **Modo laxo por defecto** (`SUPERVISOR_PRIVILEGE_STRICT=false`): la llamada denegada devuelve un sobre que el agente sobrevive. El run **termina** y la denegación **se ve en la traza**, que es más instructivo que un stack trace.

El `requirements_extractor` merece una línea aparte: su privilegio es el conjunto vacío, y además **ni siquiera importa el camino de tools**. El mínimo privilegio ahí es estructural, no una promesa.

---

## 5. La puerta humana condicional (Nivel 2)

Las puertas de la S13 pausan **siempre** — son el wizard, y está bien que lo sean. Ésta pausa ante una **señal**: el grafo corre solo cuando los números están bien anclados y para exactamente cuando no. *Una puerta que salta siempre es un formulario, no un control.*

```python
def review_reasons(state, settings=None) -> list[str]:
    reasons = []
    if confidence is not None and confidence < settings.SUPERVISOR_CONFIDENCE_THRESHOLD:
        reasons.append(f"confidence {confidence:.2f} is below the ... threshold")
    if state.get("out_of_range"):
        reasons.append("at least one component falls outside the plausible range ...")
    if total and (grounded / total) < settings.SUPERVISOR_MIN_GROUNDED_RATIO:
        reasons.append(f"only {grounded}/{total} components have any precedent ...")
    return reasons
```

Tres cosas que hacen que esto funcione:

1. **La confianza es determinista, no la que el modelo se autoinforma.** `_confidence_score` parte de la etiqueta del modelo (`low`/`medium`/`high` → 0.3/0.6/0.9), la **escala por la fracción realmente anclada** y la penaliza 0.1 por cada issue de los guardarraíles. Un `"high"` autoproclamado sobre una estimación sin precedente no pasa la puerta.
2. **El validador escribe HECHOS; la puerta es dueña del VEREDICTO.** Ese reparto es lo que permite mover el umbral por configuración —o añadir un cuarto disparador— sin tocar el validador.
3. **`review_reasons` es una función PURA de estado.** No es pulcritud, es un requisito de corrección: `interrupt()` reejecuta el nodo al reanudar, así que la rama pausa/no-pausa debe tomarse igual la segunda vez. Un disparador que leyera `datetime.now()` podría reanudar por la otra rama y asignar la respuesta del humano a la pausa equivocada.

Y la disciplina del `interrupt()`, idéntica a la de `agents/gates.py`: se llama **lo primero**, antes de cualquier escritura y **fuera** del span de Logfire. El reducer keyed es una **red de seguridad**, no el mecanismo — apoyarse en él para arreglar un orden malo escondería el bug en vez de corregirlo.

---

## 6. Auditoría (Nivel 3)

**Toda acción deja fila, incluidas las denegadas y las que no usan tool.** Sin `record_model_action` el agente sin tools sería invisible en la traza y "el run es reconstruible desde el log" dejaría de ser cierto en silencio.

Forma fija a propósito, para que un run entero se reproduzca en orden desde el log:

```bash
docker compose logs estimator | jq -c \
  'select(.event == "agent_action" and .estimation_id == "<id>")
   | [.step, .agent, .tool, .outcome, .result_summary]'
```

Las denegaciones emiten además `agent_privilege_denied` a nivel error, así que se ven sin necesidad de conocer el `estimation_id`. Y `args_preview` está acotado por `SUPERVISOR_AUDIT_ARGS_PREVIEW_CHARS`, mientras que el digest SHA-256 se registra siempre entero: la identidad de una llamada es demostrable **sin volcar una transcripción en el log**.

`privilege_violations(state)` es un *read model* derivado, deliberadamente **sin canal propio**: una violación de privilegio *es* una acción de agente, y mantenerla en la única traza ordenada es lo que hace verdadera la frase "reconstruye el run desde el log".

---

## 7. El grafo y el contrato HTTP

```
        START
          │
          ▼
   ┌─▶ supervisor ──Command(goto)──┬──▶ requirements_extractor ──┐
   │                               ├──▶ budget_searcher ─────────┤
   │                               ├──▶ estimate_generator ──────┤
   └──────── aristas de vuelta ────┼──▶ coherence_validator ─────┘
            (estáticas)            │
                                   └──▶ human_review_gate ──▶ END
```

Las cinco aristas `supervisor → {agentes, gate}` **no existen en la definición del grafo**: las dibuja `Command(goto=...)` en runtime. Ése es el punto de la sesión. Las estáticas son seis: `START → supervisor`, las cuatro de vuelta, y `gate → END`. **A `END` se llega por una sola arista**, haya pausado o no — un solo punto de salida es mucho más fácil de razonar que dos.

Los destinos se declaran **explícitamente** en `add_node(..., destinations=...)` en vez de inferirse: todos los módulos usan `from __future__ import annotations`, así que una anotación `Command[Literal[...]]` sería una cadena en runtime y la inferencia de LangGraph no sería fiable.

El contrato hacia el backend de negocio **no cambia**: transcripción in, estimación + `status` out. Lo único nuevo que el cliente debe entender es que un run puede **pausar**:

- `POST /v1/estimate/supervisor` → START; corre hasta el final o hasta la puerta.
- `POST /v1/estimate/supervisor/{id}/resume` → reanuda con `approve` / `adjust` / `reject`; **409** si no hay nada pendiente.
- `GET /v1/estimate/supervisor/{id}/state` → el snapshot, para que una UI recupere un run pausado tras cualquier demora.

Un detalle del router: `"awaiting_human_review"` es **derivado, nunca almacenado**. Mientras está pausado el run está genuinamente a mitad de nodo, y escribir ese estado antes del `interrupt()` rompería la disciplina de la que depende la puerta.

---

## 8. Divergencias respecto al oficial

| Oficial (`session_14`) | Nuestro repo | Por qué |
|---|---|---|
| CRUD Rails `supervisor_estimation_runs` sobre `estimator-web` (bandeja de revisión, badge de estado, panel de traza de enrutado y de auditoría, controlador + migración + 242 líneas de test) | **No portado** | Nuestro frontend es **Angular** (`estimator-frontend`). El contrato HTTP del servicio IA es idéntico, así que la UI se construye después contra los mismos tres verbos sin tocar este paquete. |
| Corpus histórico del profesor | **1.603 `budget_chunks` / 75 documentos** ingeridos | Nuestro corpus es más grande y genérico. Consecuencia medida, no cosmética: ver §9.4. |
| Postgres de checkpointer + pgvector | **Un solo Postgres** para checkpointer, pgvector y datos de producto | Divergencia arrastrada desde la S5, mantenida deliberadamente. |

Todo lo demás — el paquete `supervisor/`, el router, los schemas, el script y los 64 tests — es el diff oficial **fichero a fichero**.

---

## 9. Verificación (ejecución real)

### 9.1 Vía el script, contra el stack real

`uv run python scripts/run_supervisor_s14.py --out exercises/session-14/example_run_edge_case.txt`, con Postgres arriba y el corpus ingerido. Recuperación pgvector real (**175–272 ms por búsqueda**, no 0 ms como con el stub) y checkpointer `AsyncPostgresSaver`:

```
ROUTING (supervisor decisions)
  1. supervisor → requirements_extractor   [llm]
  2. supervisor → budget_searcher          [llm]
  3. supervisor → estimate_generator       [llm]
  4. supervisor → coherence_validator      [llm]
  5. supervisor → finish                   [llm]

HUMAN REVIEW
  triggered: YES
    - confidence 0.28 is below the 0.60 threshold
  decision : approve

ISSUES
  - 'Quantum Key Distribution (QKD) Implementation [integration]' has no historical reference (unbudgeted).
  - 'Visual Panel for Antenna Status [frontend]' has no historical reference (unbudgeted).
```

Las cinco decisiones salieron `source=llm`: el enrutador acertó la escalera entera sin que la guarda de legalidad tuviera que corregirlo ni una vez.

### 9.2 Una denegación real en la traza (Nivel 3)

`uv run python scripts/run_supervisor_s14.py --memory --stub --violate` hace que un agente alcance una tool que no tiene, **sin meter una llamada incorrecta en el código de producción**:

```
[error] agent_privilege_denied  agent=budget_searcher  tool=validate_estimate
        allowed=['search_budgets']  args_digest=3107f8c1e02b  step=2
```

Y el run **continúa**: las búsquedas legítimas del mismo paso se ejecutan y auditan detrás, y el flujo llega hasta el final. Exactamente el comportamiento que el modo laxo promete.

### 9.3 El ciclo humano completo por HTTP

API en el host (`uv run uvicorn`), Postgres del `docker-compose` con el checkpointer real:

| Paso | Resultado observado |
|---|---|
| **START** | `state=paused`, `status=awaiting_human_review`, `reasons=["confidence 0.41 is below the 0.70 threshold"]`, 5 decisiones de enrutado (todas `source=llm`), **17 filas** de auditoría |
| **STATE** | `state=paused`, `gate=low_confidence_review` — la pausa sobrevive al ciclo de petición: vive en el checkpoint, no en memoria |
| **RESUME** (`adjust`) | `state=completed`, `status=validated`, `human_decision` plegado en el estado, auditoría 17 → **18** filas (la fila `human/review_decision`), **cero duplicados** |
| **RESUME** de nuevo | **409** `No pending human review for this estimation_id` |

Las 17 → 18 filas son la prueba práctica del reducer keyed: el nodo se reejecutó entero al reanudar y la traza **no** creció una fila fantasma por cada acción previa.

### 9.4 Un hallazgo real: nuestro corpus deja el umbral por defecto justo en el filo

Antes de llegar a la ejecución de §9.3 hubo dos intentos que **no pausaron**, y la razón es interesante. Con nuestro corpus ingerido, la transcripción edge case **ancla todos sus componentes** (9 componentes, 41 análogos). Y entonces:

```
confidence = base(model_label) × grounded_ratio − 0.1 × issues
           = 0.6 (medium)      × 1.0            − 0        = 0.60
```

El umbral por defecto es **0.60** y la comparación es estricta (`<`), así que una estimación perfectamente anclada cuya etiqueta del modelo sea `medium` cae **exactamente sobre el umbral y no pausa**. Verificado dos veces por HTTP: `status = "validated"`, `confidence = 0.6`.

No es un bug: es la puerta haciendo su trabajo con un corpus que **sí tiene precedentes**. Solo pausa si el modelo se autoetiqueta `low`, si algún componente queda sin análogo (lo que ocurre en la traza de §9.1, `confidence 0.28`) o si los guardarraíles levantan issues. Pero significa que **con nuestro corpus el umbral útil está por encima de 0.60** — el paseo de §9.3 se ejecutó con `SUPERVISOR_CONFIDENCE_THRESHOLD=0.7`, la perilla que el propio enunciado señala como configurable, y la puerta saltó con 0.41.

Es la misma lección que el aviso del profesor sobre el corpus enlatado, vista desde el otro lado: **el umbral no es una constante universal, es una función de tu corpus**, y solo se calibra midiendo.

### 9.5 Tests sin red

```
uv run pytest tests/domain/graph/supervisor tests/api/test_estimate_supervisor.py -q
64 passed
```

- **`test_supervisor_state.py`** (9) — herencia de los reducers de la S13, idempotencia de los acumuladores keyed, el contador sin reducer, llamadas repetidas en un mismo paso.
- **`test_supervisor_routing.py`** (10) — escalera de fallback, legalidad, la búsqueda vacía que no debe hacer bucle, la elección ilegal sobreescrita, la caída del router, el presupuesto de pasos.
- **`test_privilege.py`** (12) — la tabla, "cada agente ve como mucho una tool", la denegación que **no llega** al dispatcher, el log a nivel error, el modo estricto, la tool que lanza.
- **`test_gate.py`** (11) — las tres condiciones por separado y juntas, el umbral configurable, `approve`/`adjust`/`reject`, la caída limpia sin interrumpir.
- **`test_supervisor_graph.py`** (9) — grafo end-to-end con dobles, enrutado dirigido por modelo, el extractor que nunca llama a una tool, la pausa y la reanudación sin duplicar acumuladores.
- **`test_estimate_supervisor.py`** (13) — auth, validación, 503/404/409, START completado y pausado, STATE, los tres tipos de resume.

Suite completa del repo: **534 tests** (eran 470 tras el port de S13-live). `ruff check` limpio.

---

## 10. Cómo ejecutar

```bash
# Smoke offline: sin Postgres (MemorySaver) y con retrieval enlatado.
# Solo necesita OPENAI_API_KEY para el router y los agentes LLM.
uv run python scripts/run_supervisor_s14.py --memory --stub

# Nivel 3: una denegación real en la traza, sin tocar el código de producción.
uv run python scripts/run_supervisor_s14.py --memory --stub --violate

# Ejecución real (entregable): stack arriba + corpus ingerido.
docker compose up -d postgres redis
uv run python scripts/build_task_corpus.py --ingest
uv run python scripts/run_supervisor_s14.py --out exercises/session-14/example_run_edge_case.txt

# Paseo HTTP del human-in-the-loop (ver §9.4 sobre el umbral).
ESTIMATE_API_KEY=<tu-clave> SUPERVISOR_CONFIDENCE_THRESHOLD=0.7 \
  uv run uvicorn app.main:app --host 127.0.0.1 --port 8000

# Tests (sin red, sin clave)
uv run pytest tests/domain/graph/supervisor tests/api/test_estimate_supervisor.py -v
```

> **Dos trampas locales que cuestan tiempo.** (1) El proxy de Docker también escucha en `:8000`, así que `localhost:8000` puede acabar en Docker y devolver 404 — usa **`127.0.0.1:8000`**. (2) `ESTIMATE_API_KEY` no está en nuestro `.env`, y sin ella `_verify` devuelve **401** en todas las llamadas: pásala como variable de entorno al arrancar uvicorn.

---

## 11. Lo que queda para el directo

El propio enunciado difiere tres cosas, y las tres conectan con la teoría de esta sesión:

- **Patrón de competición**: `conservative_estimator` vs `aggressive_estimator` + `synthesizer`, con la divergencia calculada en código. Nuestro `app/generation/rag/quality/synthesis.py` (S11) ya hace la mitad — mide dispersión entre **análogos históricos** y emite un rango en vez de un punto — pero no entre **supuestos**, que es lo que produce las `open_questions`.
- **Hardening de sandboxing** más allá del mínimo privilegio básico: aislamiento de proceso, políticas de red, límites de recursos. La otra frontera de seguridad, la que vive en el runtime y no en el código de aplicación.
- **Testing del flujo HITL** con más transcripciones edge case (fuera de rango, sin precedente) — hoy las tres condiciones están cubiertas por separado en `test_gate.py`, pero solo una se ha visto disparar en una ejecución real.
