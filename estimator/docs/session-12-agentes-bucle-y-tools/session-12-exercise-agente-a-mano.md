# Sesión 12 — Ejercicio resuelto: un agente hecho a mano (bucle manual sobre la Responses API)

> Resolución del ejercicio previo a la Sesión 12 ("Introducción a agentes de IA 🔴").
> Resuelto **igual que el profesor** (rama oficial `session_12`, commit `492d467` — "solved pre exercise session 12"), **adaptado a las divergencias de nuestro repo**.
> Alcance del enunciado: un agente que descompone una transcripción en componentes, usa `search_budgets` + `calculate_estimate` (+ la `validate_estimate` opcional) en un **bucle manual reason→act→observe**, y devuelve una estimación estructurada **junto a su traza**. Sin framework, sin endpoint HTTP ni UI (eso lo añade la sesión en vivo).

---

## 0. Punto de partida y estrategia

Como en la Sesión 11, partimos de un servicio IA **ya convergido con el oficial** tras los ports de `session_09_live`/`session_10_live`/`session_11_live` (ver [`estimator-session11-live-port`](../../../../.claude/projects/-Users-borjagarciacueto-Documents-Claude-Projects-ai-engineering/memory/estimator-session11-live-port.md)). Eso significa que las piezas de las que depende el agente — `retrieve()` (`app/generation/rag/retrieval/pipeline.py`), `Collection.BUDGET`, `RetrievedChunk` con `estimated_hours`, `get_embedder()`, `get_settings()` — son **idénticas** a la base oficial, así que el diff del profesor se aplica **casi literal**.

Decisión: **portar el diff oficial fichero a fichero**, adaptando solo lo mínimo (nada, en la práctica: los puntos de integración coincidían byte-a-byte). No se reimplementó nada del pipeline de recuperación — el agente solo lo *invoca* a través de una tool, que es justo lo que pide el enunciado ("`search_budgets` envuelve tu retrieval; no lo reconstruyas").

### 0.1 La única divergencia real: ya teníamos una capa `agentic/`, pero no era esto

Nuestro `app/generation/agentic/` ya contenía el bucle **Actor-Critic-Boss** (`boss.py` + `critic.py`) de las sesiones 4/5. Conviene no confundirlos, porque la teoría de esta sesión los separa con precisión:

- **ACB (`boss.py`/`critic.py`)** es un *workflow* sofisticado: el control de flujo lo escribimos **nosotros** (el Boss es una máquina de estados `actor→critic→decide`; "no hace LLM calls de su propia"). El modelo rellena huecos, no elige el siguiente paso.
- **El agente de S12 (`agent_loop.py`)** es un *agente* en el sentido estricto del enunciado: el **modelo** decide qué tool usar y en qué orden, y el bucle solo ejecuta lo que pide y le devuelve la observación.

Los dos coexisten en el mismo paquete sin tocarse. Se actualizó solo el docstring de `agentic/__init__.py` para nombrar ambos. Esta es la razón por la que el nombre de fichero del agente es `agent_loop.py` (no `boss.py`): son animales distintos.

---

## 1. Qué se construyó

Cinco piezas de código + un kit de estudiante, todo dentro del servicio IA:

| Fichero | Rol |
|---|---|
| `app/generation/agentic/agent_schemas.py` | Modelos Pydantic: argumentos de tools (validados **antes** de despachar), traza (`AgentStep`/`AgentTrace` con `render()` en formato `STEP N`), y el resultado **ligero** `AgentEstimate`. |
| `app/generation/agentic/agent_tools.py` | Los 3 schemas **planos** `strict:true` de la Responses API + sus implementaciones + `dispatch_tool`. |
| `app/generation/agentic/agent_loop.py` | `run_estimation_agent`: el bucle manual reason→act→observe sobre `client.responses.create`/`.parse`. |
| `scripts/run_agent_s12.py` | Demo ejecutable (CLI: `--model`/`--effort`/`--max-iterations`/`--stub`/`--out`). Genera el entregable. |
| `app/config.py` + `app/dependencies.py` | 5 vars `AGENT_*` + `get_async_openai_client()`. |
| `exercises/session-12/` | Kit del estudiante: 2 transcripciones, stub de retrieval offline, esqueleto de `calculate_estimate`, README, y la traza-entregable. |
| `tests/generation/agentic/` | Tests sin red (matemática de tools + control del bucle con un `AsyncOpenAI` falso). |

---

## 2. Las tres tools (`agent_tools.py`)

Todas se declaran con el **schema plano** de la Responses API (`{"type": "function", "name": ..., "parameters": {...}}`, **no** anidado bajo `function` como en Chat Completions) y `strict: true` — lo que obliga a que cada propiedad esté en `required` (la opcionalidad se modela con uniones nullable, p. ej. `["object", "null"]`) y `additionalProperties: false` en **todos** los niveles.

- **`search_budgets(query, filters?)`** — **envuelve `retrieve()`** vía un *backend inyectable* (`RetrievalBackend`). El backend por defecto (`default_retrieval_backend`) embebe la query con `get_embedder().embed_one`, corre `retrieve()` sobre `Collection.BUDGET` filtrado a `chunk_type='historical_task'` (los chunks que llevan las horas históricas), y aplana cada chunk a `{id, content_preview, sector, budget_id, estimated_hours, distance}`. El *stub* del kit se inyecta en su lugar para depurar el bucle sin base de datos.
- **`calculate_estimate(components)`** — determinista, **sin LLM**: por componente toma la **mediana** de las `reference_amounts` (robusta a un outlier), le suma un `CONTINGENCY_FACTOR` fijo del 15 %, y suma el total. Si un componente no tiene referencias, lo cuesta a `0` y lo marca `unbudgeted=True` en vez de inventar un número — para que el agente lo note y vuelva a buscar.
- **`validate_estimate(components, total_hours)`** (la extensión opcional, incluida) — guardrails estilo S4, sin LLM: marca componentes sin referencia, horas fuera del rango plausible `[min·0.5, max·2]` de sus referencias, un total que no cuadra con la suma, y totales no positivos o > 20.000 h.

> **La descripción es la interfaz.** Es lo único que el modelo lee para decidir cuándo usar cada tool. La de `search_budgets` lleva dentro la restricción "una llamada por componente" y un ejemplo — es exactamente la palanca que la Parte 5 de la teoría describe, y lo que en el directo se optimiza mirando trazas.

Ante un argumento inválido o alucinado, `dispatch_tool` (y la validación Pydantic previa) **lanzan**, y el bucle mapea la excepción a un string de error que devuelve al modelo como observación — nunca mata el bucle.

---

## 3. El bucle (`agent_loop.py`)

Es la pieza central del ejercicio, y es corto:

1. **Primera llamada** `responses.create` con el `SYSTEM_PROMPT` (rol + método de 5 pasos), la transcripción como `input`, `tools=TOOL_SCHEMAS` y `reasoning={"effort": …, "summary": "auto"}` (el `summary` es lo que surface el resumen de razonamiento para la traza).
2. **En cada vuelta**: recoge **todos** los items `function_call` de `response.output`. Si no hay ninguno → parada natural, se sale. Ejecuta cada llamada (varias en la misma vuelta = llamadas en paralelo del modelo), registra cada una en la traza (`reasoning + action + observation`), y devuelve todos los `function_call_output` — **cada uno con su `call_id`** — en una única llamada de continuación.
3. **Encadenado con estado**: `store=True` + `previous_response_id` + reenviar **solo** los outputs nuevos. El servidor conserva el orden de los items de razonamiento/tool-call, lo que sortea los *pitfalls* de ordenación de items de razonamiento de gpt-5.
4. **Guarda de parada**: `max_iterations` (default 10) además de la parada natural. Un bucle sin techo es una factura esperando a dispararse.
5. **Salida estructurada terminal**: una última `responses.parse(text_format=AgentEstimate)` convierte el contexto acumulado en un `AgentEstimate` validado. La no-determinación vive dentro del bucle; el contrato de salida es determinista.

**Detalle de traza (fiel a gpt-5):** el modelo razona **una vez por vuelta** aunque emita varias tool calls paralelas, así que el resumen de razonamiento se adjunta al primer paso de la vuelta y los hermanos se marcan `(parallel tool call in the same turn as STEP N)` en vez de repetir el bloque entero.

### 3.1 La excepción deliberada a la regla del `LLMWrapper`

Todo el resto del código habla con los LLM a través de `LLMWrapper` (LiteLLM + Instructor). **Este módulo habla con la Responses API cruda a propósito** (`client.responses.create`/`.parse`), porque *ver el bucle a mano es el objetivo del ejercicio*. Está documentado en el docstring del módulo con un "no lo 'arregles' para usar `LLMWrapper`". Por eso se añadió `get_async_openai_client()` (un `AsyncOpenAI` cacheado) — el bucle es `async` (corre junto al `retrieve()` async que envuelve su tool), y el cliente sync existente no sirve.

---

## 4. Configuración (`config.py`)

Cinco vars nuevas, **plain settings** (no runtime-config: no hay endpoint en vivo esta sesión):

- `AGENT_MODEL` = `gpt-5`, `AGENT_REASONING_EFFORT` = `medium` — el script los sobreescribe por invocación (`gpt-5-mini` para depurar barato).
- `AGENT_MAX_ITERATIONS` = `10` — la guarda del bucle (1 iteración = 1 round-trip a la API).
- `AGENT_SEARCH_TOP_K` = `5`, `AGENT_SEARCH_DISTANCE_THRESHOLD` = `0.6` — lo que la tool `search_budgets` pasa a `retrieve()`. Un poco más holgado que los defaults de RAG: el agente lanza muchas queries estrechas por componente y se beneficia de algún candidato más.

---

## 5. Verificación (ejecución real)

El enunciado marca cinco criterios de aceptación sobre `sample_transcript_complex.txt`. Se ejecutó el agente de verdad (`gpt-5-mini`, `--effort low`, `--stub` para no necesitar la base de datos), y los cumple todos:

```
$ uv run python scripts/run_agent_s12.py \
    exercises/session-12/sample_transcript_complex.txt --model gpt-5-mini --effort low --stub

agent_run_start                effort=low model=gpt-5-mini
agent_tool_search_budgets      query='Backend business API for logistics: ...'                results=2
agent_tool_search_budgets      query='SAP ERP integration: IDoc mapping, middleware ...'      results=5
agent_tool_search_budgets      query='Mobile app for delivery drivers (Android + iOS) ...'    results=3
agent_tool_search_budgets      query='Analytics dashboard for logistics: KPIs ...'            results=2
agent_tool_calculate_estimate  components=4 total_hours=3415.5
agent_tool_validate_estimate   issues=0 ok=True
agent_run_done                 iterations=5 steps=6 stopped_reason=completed total_hours=3415.5
```

| Criterio de aceptación | Resultado |
|---|---|
| Identifica > 1 componente y hace > 1 `search_budgets` | ✅ 4 componentes, 4 búsquedas (en paralelo en la primera vuelta) |
| Llama a `calculate_estimate` con componentes y referencias | ✅ 4 componentes con sus `reference_amounts` |
| Termina por sí solo (ni bucle infinito ni corte a mitad) | ✅ `stopped_reason=completed`, 5 iteraciones |
| Produce una estimación estructurada coherente | ✅ `AgentEstimate` validado, total 3415,5 h, `confidence=medium` |
| La traza muestra razonamiento + acción + observación por paso | ✅ 6 pasos en formato `STEP N` |

La traza completa (con el razonamiento, las 4 búsquedas, el `calculate_estimate`, el `validate_estimate` y la estimación final con fuentes y asunciones) queda en [`exercises/session-12/example_trace_complex.txt`](../../exercises/session-12/example_trace_complex.txt) — **el entregable**.

Comportamiento emergente que ilustra por qué el bucle importa: en la ejecución del profesor con `gpt-5` (retrieval real), la búsqueda de la integración SAP con el filtro `sectors=['logistics']` volvió **vacía**; el agente **leyó esa observación, ensanchó la búsqueda quitando el filtro de sector**, y solo entonces calculó. Ese reintento no lo programamos nosotros: emergió de que el modelo pudo ver el resultado de su propia acción. Es exactamente lo que un pipeline fijo no puede hacer.

### 5.1 Tests sin red

`tests/generation/agentic/` (15 tests, 0 llamadas de red) cubren:
- **Tools** (`test_agent_tools.py`): mediana + contingencia, flag de `unbudgeted` sin inventar horas, suma de componentes, guardrails de `validate_estimate` (rango, mismatch de total, total no positivo), rechazo de argumentos malos, backend inyectable, y `dispatch_tool` con tool desconocida.
- **Bucle** (`test_agent_loop.py`, con un `AsyncOpenAI` falso scripteado): camino feliz multi-tool (2 búsquedas → calcular → validar → fin), *echo* correcto de `call_id`, la guarda `max_iterations`, y que un argumento inválido se convierte en observación de error **sin** romper el bucle.

Suite completa del repo: **420 tests verdes** (405 previos + 15 nuevos).

---

## 6. Cómo ejecutar

```bash
cd estimator

# Depuración offline con el stub (SIN base de datos) — lo usado en §5
uv run python scripts/run_agent_s12.py \
    exercises/session-12/sample_transcript_simple.txt --model gpt-5-mini --stub

# Ejecución real (retrieval de verdad: stack arriba + corpus de tareas ingerido)
docker compose exec estimator python scripts/build_task_corpus.py --ingest
docker compose exec estimator python scripts/run_agent_s12.py \
    exercises/session-12/sample_transcript_complex.txt --model gpt-5 --effort medium \
    --out exercises/session-12/example_trace_complex.txt

# Tests (sin red)
uv run pytest tests/generation/agentic/ -q
```

---

## 7. Divergencias respecto al oficial (resumen)

| Aspecto | Oficial `session_12` | Nuestro repo |
|---|---|---|
| Código del agente (schemas/tools/loop) | commit `492d467` | **idéntico** (puntos de integración ya convergidos) |
| Kit del estudiante + tests | `exercises/session-12/` + `tests/generation/agentic/` | **idéntico** |
| `CLAUDE.md` con design point S12 | sí | nuestro repo **no mantiene** `CLAUDE.md` — el design point vive en este doc y en la memoria |
| Traza-entregable | run de `gpt-5` + retrieval real | **nuestra** run de `gpt-5-mini` + stub (reproducible sin DB); misma forma y criterios cumplidos |
| Doc de sesión en `docs/` | no (el oficial usa `exercises/.../README.md`) | **sí** — este fichero, por la convención `session-NN-exercise-*` del resto de nuestras sesiones |
