# Sesión 6 — Stress test del CAG: medir dónde rompe 🔴

> Este documento describe **solo los cambios del ejercicio previo a la sesión 6** y sirve
> de guía para seguir el ejercicio paso a paso. Para la guía completa del backend pieza a
> pieza, ver [`codigo-explicado.md`](../codigo-explicado.md) (sección 19). Aquí se cuenta
> *qué se tocó*, *por qué* y *cómo reproducirlo*, no se reexplica el CAG que ya existía.
>
> Implementación basada en el repo oficial del profesor (commit *“session 06 exercise: CAG
> stress test scaffolding”*), adaptada a los desvíos de esta implementación (Postgres,
> telemetría `LlmUsage`, frontend Angular). Las divergencias se señalan a lo largo del texto.

## 1. Objetivo

Hasta la sesión 5 el sistema es un **CAG (Cache-Augmented Generation)**: cada turno inyecta
en el prompt *todo* el contexto disponible —`[resumen] + anchors + ventana_deslizante +
ProjectMetadata + tier + transcripción + texto_extraído_de_adjuntos`— y confía, por
construcción, en que todo cabe en la ventana del modelo. Funciona mientras los proyectos
son cortos y los adjuntos modestos. **Nunca lo hemos puesto a prueba en serio.**

No sabemos a qué turno empieza a olvidar el nombre del proyecto, ni cuánto cuesta el turno
20 frente al turno 1, ni a qué tamaño de adjunto la latencia P95 supera el SLA del cliente.

Este ejercicio **no añade una capacidad nueva**: instrumenta el CAG, lo somete a tres
escenarios de carga (multi-turno largo, adjuntos grandes, contradicciones), y produce un
`REPORT.md` con tres curvas y dos párrafos de lectura. El entregable es un **baseline
cuantitativo** del CAG; en la sesión en vivo se compara contra RAG.

> **La gracia es medir, no optimizar.** Acortar el `system`, comprimir más agresivo o bajar
> `MAX_CONVERSATION_TURNS` mover­ía una constante e invalidaría la comparación. El ejercicio
> mide; el módulo 3 (sesión 6 en vivo) introduce RAG como respuesta a las limitaciones que
> el alumno haya medido **con sus propios datos**.

## 2. Decisiones de diseño

### 2.1 Un único evento agregado por turno (Bloque 1)

El pipeline ya emitía señales sueltas (`cache_hit`, `llm_call_completed`,
`history_compressed`, `session_estimate_received`). Para extraer un CSV de una sola pasada
eso obliga a reconciliar varias líneas de log por *timestamp*. Se añade **un único evento**
`turn_observed` con los 13 campos relevantes juntos, y —además— se devuelve esa misma
observación embebida en la respuesta JSON.

- **Por qué un evento agregado:** el runner lee `response.observation` directamente del JSON
  —cero parseo de logs, correlación trivial entre `messages_in_window` y `cost_usd`, sin
  reconciliar timestamps—.
- **Por qué también en el JSON y no solo en el log:** el enunciado deja elegir entre parsear
  `docker compose logs | grep turn_observed` o exponer una versión enriquecida vía la
  respuesta. Se elige **embeber en la respuesta**: es determinista, no depende del formato
  del log ni del transporte de Docker, y el runner queda independiente de dónde corra el
  estimator.

### 2.2 Métricas en módulo aparte (Bloque 4)

Las tres métricas nuevas operan sobre una `TurnObservation` + un *snapshot* de sesión, **no**
sobre `(GoldenCase, EstimationResult)` como las de `evals/metrics.py`. Por ese desajuste de
firma viven en `evals/stress/metrics.py`. Pero **reutilizan el `MetricResult`**
(`name, score, passed, details`) tal cual, para que la forma del reporte sea uniforme.
Determinismo > sofisticación: nada de embeddings ni LLM-as-judge.

### 2.3 Desvíos respecto al repo oficial

| Tema | Oficial | Esta implementación |
|------|---------|---------------------|
| Tokens en el `meta` del wrapper | `tokens_in` / `tokens_out` | `input_tokens` / `output_tokens` → se **mapean** al construir la `TurnObservation` |
| Store de sesiones | `SessionStore` en memoria | `DbSessionStore` (Postgres). El branch en proceso del runner sobreescribe `get_db` con sqlite, no `get_session_store` |
| Telemetría existente | solo `cached` | ya existía `usage: LlmUsage`; `observation` se añade **además**, sin tocar `usage` |
| Frontend | Rails (`estimator-web`) | Angular (`estimator-frontend`) — el ejercicio es backend puro, no toca UI |

## 3. Cambios en el backend (`estimator/`)

### Archivos nuevos

- `evals/stress/__init__.py` — docstring del paquete.
- `evals/stress/scenarios.py` — los tres escenarios de 20 turnos con fact-trackers.
- `evals/stress/metrics.py` — `LatencyBudgetMetric`, `CostBudgetMetric`, `MemoryDriftMetric`.
- `evals/stress/fixtures/__init__.py` — paquete vacío.
- `evals/stress/fixtures/build_pdfs.py` — generador determinista de PDFs sintéticos.
- `evals/stress/run.py` — runner CLI (`--http`, `--scenarios`, `--attachment-sizes`, `--repeats`).
- `evals/stress/REPORT.md` — esqueleto del entregable.
- `tests/test_stress_metrics.py` — 15 tests unitarios de las métricas.
- `tests/test_stress_runner.py` — 2 smoke tests del runner con `FakeLLMWrapper`.

### Archivos modificados

- `app/schemas/estimation.py` — modelo **`TurnObservation`** (13 campos) + campo opcional
  `observation: TurnObservation | None` en `EstimationResponse`. Import de `Literal`.
- `app/services/estimation.py` — `estimate_conversational` recibe
  `attachments_total_chars`, captura `turn_index` **antes** de comprimir, construye la
  `TurnObservation`, emite `log.info("turn_observed", …)` y la adjunta a la respuesta.
- `app/routers/sessions.py` — `_resolve_session_and_enrich` ahora devuelve
  `(session, enriched, attachments_total_chars)`; `estimate_in_session` pasa ese tamaño al
  servicio; `estimate_in_session_acb` lo descarta (el camino ACB no emite observación).
- `pyproject.toml` — nueva dependencia `fpdf2>=2.7` (solo para generar los PDFs sintéticos).
- `.gitignore` — ignora los artefactos regenerables: `fixtures/*.pdf`, `results.csv`,
  `smoke.csv`.

### El flujo de un turno instrumentado

```
POST /sessions/{id}/estimate   (multipart: transcript + adjuntos)
  └→ routers/sessions.py::_resolve_session_and_enrich
        · extrae texto de adjuntos → enriched
        · attachments_total_chars = suma de texto crudo extraído
  └→ services/estimation.py::estimate_conversational(attachments_total_chars=…)
        1..7  (igual que sesión 5: guardrail, tier, prompt v3, LLM, compresión, metadata)
        ·  turn_index = len(history.messages) // 2   ← capturado ANTES de comprimir
        8.  observation = TurnObservation(13 campos)   ← tokens_in/out mapeados de input/output_tokens
            log.info("turn_observed", **observation.model_dump())
        return EstimationResponse(result, …, usage, observation)
```

El `turn_index` se captura antes de la compresión porque, una vez la ventana deslizante
toca su tope, `len(messages) // 2` se estanca y dejaría de reflejar el número real de turno
—justo el eje X de dos de las tres curvas—.

## 4. Los tres escenarios (Bloque 2 — `evals/stress/scenarios.py`)

Cada escenario es una lista de `ScenarioTurn(transcript, fact_introduced, fact_field)` y un
`dataclass Scenario` que exige ≥20 turnos en `__post_init__`.

| Escenario | Proyecto | Qué fuerza | Hecho del turno 1 |
|-----------|----------|------------|-------------------|
| `growing` | Nimbus (B2B SaaS) | Expulsión de la ventana: ¿sobrevive el turno 1 al turno 20? | `Nimbus` (`project_name`) |
| `pivot` | Helios (app móvil) | Turno 5: React Native → Flutter. ¿`mentioned_technologies` acumula o pierde? | `Helios` (`project_name`) |
| `contradiction` | Atlas (interno) | Turno 3: 30k €; turno 8: 80k €. ¿Qué versión sobrevive? | `Atlas` (`project_name`) |

El runner rastrea el hecho del **turno 1** de cada escenario (los tres son `project_name`),
así que `MemoryDriftMetric` mide la pregunta canónica: *“¿sigue vivo el nombre del proyecto
del inicio en el turno N?”*.

## 5. Las tres métricas (Bloque 4 — `evals/stress/metrics.py`)

```python
LatencyBudgetMetric(budget_ms=8000)   # 1.0 si latency_ms <= budget_ms
CostBudgetMetric(budget_usd=0.02)     # 1.0 si cost_usd <= budget_usd (coste de UN turno)
MemoryDriftMetric(fact, fact_field)   # 1.0 si el fact aparece en el slice del snapshot
```

`MemoryDriftMetric` hace match de substring *case-insensitive*. El `fact_field` acota dónde
buscar: `project_name`, `technologies`, `scope`, `summary` o `any` (serializa el snapshot
entero). Es determinista: cuando dice que el hecho desapareció, desapareció.

> **Los presupuestos son contratos de diseño, no banderas a observar a posteriori.** Una
> `LatencyBudgetMetric(budget_ms=8000)` convierte el SLA del cliente en un test booleano por
> turno —igual que los validadores de `EstimationResult` convirtieron las reglas de negocio
> en re-prompts—.

## 6. El corpus de adjuntos (Bloque 3 — `fixtures/build_pdfs.py`)

```bash
uv run python -m evals.stress.fixtures.build_pdfs
```

Genera `attach_{5,20,50,100}kb.pdf` donde el sufijo es el **texto extraído** (lo que saca
`pypdf`), no el peso en disco. Determinista (mismo párrafo, mismas repeticiones). **No se
comitean**: están en `.gitignore` y el runner los regenera.

| Tamaño | Texto extraído real | Notas |
|--------|--------------------|-------|
| 0 KB | — | baseline, sin adjunto |
| 5 KB | ~5 455 chars | ≈ 2 páginas |
| 20 KB | ~20 732 chars | ≈ 8 páginas |
| 50 KB | ~51 286 chars | ≈ 20 páginas |
| 100 KB | ~102 573 chars | **régimen truncado**: por encima de `MAX_ATTACHMENT_CHARS=60 000` |

## 7. El runner y el CSV (Bloque 5 — `evals/stress/run.py`)

Orquesta `escenarios × tamaños × repeticiones`. Por turno: `POST …/estimate` →
lee `response.observation` → `GET /sessions/{id}` para el snapshot → escribe una fila de CSV
(22 columnas: toda la telemetría + `wall_clock_ms` + 3 veredictos booleanos + `tracked_fact`
+ `error`). Al final imprime un resumen P50/P95 por celda.

```bash
# 1) Levanta el estimator real (LLM real, PDFs reales)
docker compose up --build -d
curl -sf http://localhost:8000/health

# 2) Regenera los PDFs (deterministas)
uv run python -m evals.stress.fixtures.build_pdfs

# 3) Corre el stress test contra el servicio real
uv run python -m evals.stress.run \
    --http http://localhost:8000 \
    --scenarios growing,pivot,contradiction \
    --attachment-sizes 0,5,20,50,100 \
    --repeats 3 \
    --latency-budget-ms 8000 \
    --cost-budget-usd 0.02 \
    --output evals/stress/results.csv

# 4) Sanity check (≥ 50 filas + cabecera)
wc -l evals/stress/results.csv
```

> **Desvío del oficial en el transporte en proceso.** Sin `--http`, el runner monta un
> `TestClient`. El profesor sobreescribe `get_session_store` con un `SessionStore` en memoria;
> aquí, como el store es Postgres sobre `get_db`, se sobreescribe **`get_db`** con un sqlite en
> memoria (el patrón de `tests/conftest.py`) y `get_session_store` lo usa de forma
> transparente. Ese camino sigue usando el LLM real (necesita API key); el *smoke* offline vive
> en los tests, que llaman a `_run_one_session` con el `FakeLLMWrapper`.

## 8. El reporte (`evals/stress/REPORT.md`)

Es el **entregable** que se lleva al directo. El repo trae el esqueleto pre-poblado con la
forma esperada; se rellena a mano con los números del CSV:

1. **Tabla resumen** — una fila por `(escenario, tamaño)`: P50/P95 latencia, coste total,
   % de aprobado de drift.
2. **Tres curvas como tablas** (sin gráficos): latencia vs `tokens_in`; coste acumulado vs
   turno; drift vs N.
3. **Dos párrafos de lectura** — *“¿a partir de qué turno empieza a romperse mi CAG?”*,
   *“¿qué dimensión domina la degradación: latencia, coste o pérdida de memoria?”*,
   *“¿qué caso límite justifica saltar a RAG?”* — con al menos una afirmación cuantitativa
   concreta del tipo *“a partir del turno N=12 el recall del project_name cae bajo el 60%”*.

## 9. Verificación

```bash
cd estimator

# Suite completa (incluye los 17 tests nuevos del stress)
uv run pytest -q            # 186 passed  (169 → 186, +17)

# Solo los tests del ejercicio
uv run pytest tests/test_stress_metrics.py tests/test_stress_runner.py -q   # 17 passed

# Lint
uv run ruff check .
```

Los 17 tests nuevos = 15 unitarios de métricas (un aprobado, un fallo y un caso límite por
métrica) + 2 smoke del runner (cableado `observation`→CSV→métricas con el `FakeLLMWrapper`,
sin gastar crédito de LLM).

## 10. Ejecución real: dos ajustes y los hallazgos

Correr el stress contra un LLM real obligó a tocar dos piezas. Son **desvíos
conscientes para poder medir**, no mejoras del CAG. La sección *History* de
`evals/stress/REPORT.md` cuenta los tres intentos (sonnet → rate limit;
gpt-4o-mini con la regla → 502 de validación; gpt-4o-mini sin la regla → run
limpio).

### 10.1 El flag `ENFORCE_PHASES_SUM`

`gpt-4o-mini` no hace que las fases sumen `total_cost_eur` de forma fiable (se
equivoca ~20%). Con el validador `phases_sum_matches_total` activo, Instructor
agota sus reintentos y el turno devuelve **502** — el ~57% de los turnos morían en
el turno 1. Se añadió `ENFORCE_PHASES_SUM` (`config.py`, default `True`); el
validador lo lee vía `get_settings()` y **salta solo esa regla** cuando está en
`False`. El stress run lo pone a `false` en `.env`; **producción lo mantiene en
`true`**. Medimos latencia/coste/memoria, no la exactitud del euro. Test nuevo:
`test_phases_sum_check_skipped_when_disabled`.

### 10.2 El `turn_index` real en el runner

`TurnObservation.turn_index` se calcula en el servidor como
`len(history.messages) // 2`. Como la ventana deslizante recorta el historial
cada turno, **se estanca en `MAX_CONVERSATION_TURNS + 1 = 7`** — inservible como
eje "turno" de las curvas. El runner conduce la conversación y conoce el turno
real, así que ahora **escribe en el CSV el índice de su bucle** (`turn_number`),
sobreescribiendo el valor del servidor.

### 10.3 Qué salió (resumen del REPORT)

- **Run limpio:** 780 filas, ~1% de error, 38/45 sesiones a 20 turnos. Coste total ~$3.49.
- **El cuello de botella es la latencia,** no la memoria ni el coste: P50 sube de
  ~5 s (0 KB) a ~24 s (100 KB); solo el **33%** de los turnos bajó del SLA de 8 s.
- **El coste por turno nunca fue problema** en mini (100% bajo $0.02), pero el
  total **escala ~12× con el adjunto** ($0.05 → $0.63 por celda). El adjunto manda.
- **Drift = 100% en todo** — pero es un **no-resultado estructural**: el hecho
  rastreado (`project_name`) vive en `ProjectMetadata`, inmune a la expulsión de
  la ventana, y `anchors_count` fue 0 siempre. Para medir drift real habría que
  rastrear un hecho que viva *solo* en la ventana.
- **Lectura para RAG:** el adjunto se reinyecta entero cada turno y dispara la
  latencia; RAG traería solo el trozo relevante. El caso límite que justifica el
  salto: con adjuntos ≥ 50 KB, **cada turno incumple el SLA de 8 s**.

El entregable es [`evals/stress/REPORT.md`](../../evals/stress/REPORT.md) +
`results.csv` (gitignored).
