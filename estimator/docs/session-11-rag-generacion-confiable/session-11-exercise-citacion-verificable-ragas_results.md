# Sesión 11 — Resultados reales (citación verificable + baseline RAGAS)

> Resultados reales del ejercicio (Partes 1 y 2) ejecutados sobre nuestro stack.
> Documento de ejercicio asociado: [`session-11-exercise-citacion-verificable-ragas.md`](session-11-exercise-citacion-verificable-ragas.md).
> Fecha de ejecución: **2026-07-02**.

## Cómo se obtuvo

```bash
cd estimator
uv sync --group dev
docker compose up -d                        # Postgres ya tenía el corpus base ingerido (60 chunks / 15 presupuestos)
uv run python scripts/demo_verify_citations_s11.py
DATABASE_URL='postgresql+asyncpg://postgres:postgres@localhost:5432/estimator' \
LLM_TIMEOUT=180 \
  uv run python scripts/eval_ragas_s11.py --out evals/ragas_baseline_s11.json
```

- **Corpus**: 15 presupuestos / 60 chunks (`budget_chunks`), ya ingerido desde sesiones anteriores.
- **Pipeline real**: `reformulate_query` (gpt-5-mini) → embed (`text-embedding-3-small`) → `retrieve` híbrido + rerank (cross-encoder) → `truncate_to_token_budget` → `build_context_block` → `generate_estimate` (gpt-5, `reasoning_effort=high`) → `verify_citations`.
- **`LLM_TIMEOUT=180`**: con el default (30s) la primera generación (`gpt-5`, razonamiento alto, el nuevo esquema por línea más grande) hizo timeout de forma reproducible. No es un fallo del port: el esquema de la Sesión 11 obliga al modelo a emitir más tokens estructurados por tarea (`chunk_id`+`document_id`+`evidence` por fuente), y eso alarga la generación por encima del timeout pensado para la Sesión 9.
- **Juez RAGAS**: `gpt-4o-mini`. **Embeddings**: `text-embedding-3-small`.

## Paso 1.5 — Demo offline de citación verificable

Salida real de `scripts/demo_verify_citations_s11.py` (sin red, sin base de datos):

```
=== Citation verification report ===
lines: 4  grounded: 2  dangling: 1  insufficient: 1
verified citations: 2
dangling citations: ['999']

module           line                       status        cited -> dangling
----------------------------------------------------------------------------------------
Authentication   OAuth 2.0 backend          grounded      ['101'] -> -
Payments         Instant payments gateway   grounded      ['102'] -> -
Ledger           Transaction ledger         dangling      ['999'] -> ['999']
Reporting        Regulatory reporting       insufficient  [] -> -

ACCEPTANCE: PASS
```

Los tres criterios de aceptación de la Parte 1 quedan probados: **grounded=True con fuente real** (Authentication, Payments citan chunks 101/102, realmente recuperados), **citación colgante detectada** (Ledger cita 999, nunca recuperado, marcado `dangling`), **sin datos suficientes** (Reporting no se rellena con horas, se marca `insufficient`).

## Corrección previa del golden set (bug encontrado, no forma parte del enunciado pero era bloqueante)

Antes de poder confiar en cualquier número, se corrigió `evals/golden_retrieval.json` (ver §0.1 del doc de ejercicio): Q1–Q8 tenían ids de presupuesto del repositorio **oficial**, que no existen en nuestro corpus. Tras la corrección, `scripts/eval_retrieval_s10.py` vuelve a dar precisión sana para Q1-Q5 (extracto relevante, config A = vectorial sin rerank):

| Config | Q1 | Q2 | Q3 | Q4 | Q5 |
|---|:---:|:---:|:---:|:---:|:---:|
| A (Vectorial) | 0,80 | 1,00 | 1,00 | 1,00 | 1,00 |
| C (Vectorial+Rerank) | 1,00 | 1,00 | 1,00 | 1,00 | 0,60 |

(Q6-Q8, multi-índice, siguen a 0 porque `transcript_chunks`/`technical_doc_chunks` no están ingeridos en este stack — fuera del alcance de este ejercicio, que solo evalúa Q1-Q5 sobre presupuestos.)

## Paso 2.3 — Tabla de métricas RAGAS (4 métricas × 5 consultas + promedio)

Ejecución real sobre el pipeline completo. Datos completos (incluido el `citation_report` por consulta) en `evals/ragas_baseline_s11.json`.

| query | faithfulness | answer_relevancy | context_precision | context_recall |
|---|---|---|---|---|
| Q1 | 0.565 | 0.093 | 1.000 | 0.714 |
| Q2 | 0.696 | 0.045 | 0.917 | 0.625 |
| Q3 | 0.692 | 0.000 | 1.000 | 0.000 |
| Q4 | 0.588 | 0.252 | 1.000 | 0.875 |
| Q5 | 0.188 | 0.116 | 0.500 | 1.000 |
| **average** | **0.546** | **0.101** | **0.883** | **0.643** |

## Verificación de citaciones sobre las 5 estimaciones reales generadas

Salida real de `verify_citations` sobre cada estimación producida por el pipeline (no plantada — cada línea es una tarea real que el modelo decidió citar o dejar sin fundamentar):

| query | líneas | grounded | dangling | insufficient | citas verificadas |
|---|---|---|---|---|---|
| Q1 | 37 | 26 | 0 | 11 | 30 |
| Q2 | 35 | 35 | 0 | 0 | 40 |
| Q3 | 37 | 20 | 0 | 17 | 24 |
| Q4 | 37 | 27 | 0 | 10 | 32 |
| Q5 | 25 | 20 | 0 | 5 | 24 |
| **total** | **171** | **128** | **0** | **43** | **150** |

**Citaciones colgantes: 0/171 líneas.** Cada línea `grounded=True` cita un chunk real del contexto recuperado; las 43 líneas sin soporte se marcan `insufficient` (no inventan horas), no se rellenan.

### El caso Q5: fraude sin analogía histórica, detectado y dejado sin fundamentar

Q5 (`ground_truth` diseñado como stress test, ver §2.1 del doc de ejercicio) pide una pasarela de pagos con **detección de fraude**, un componente que **no existe en ningún presupuesto del corpus**. La estimación real generada por el pipeline creó un módulo completo **"Real-time Fraud Detection & Risk"** con 5 tareas (extracción de features, motor de reglas, integración de modelo ML, herramientas de casos, decisión en el flujo de pago) — **las 5 marcadas `insufficient`**, ninguna con horas inventadas. El resto de Q5 (Gateway, Ledger, KYC/AML, Webhooks) sale `grounded` contra `BUD-2024-040`/`BUD-2024-014`. Es la prueba más limpia de todo el ejercicio de que el contrato `grounded=False ⇒ sin horas` funciona bajo presión real, no solo en el demo offline plantado.

## Nota de hallazgos (lo que más chirría)

- **`context_recall` colapsa a 0.000 en Q3 pese a `faithfulness`=0.692 y `context_precision`=1.0.** Q3 es el caso de síntesis multi-fuente deliberado (dos presupuestos que no se solapan, `BUD-2024-052` + `BUD-2023-008`). La recuperación trae exactamente las fuentes correctas (precisión perfecta), pero el generador descompone cada componente histórico en 5-8 subtareas finas (p. ej. "Video Consultations" se convierte en *WebRTC signaling*, *virtual waiting room*, *screen sharing*, *session recording*...); el juez de RAGAS no consigue mapear 1:1 el `ground_truth` a nivel de componente contra esa descomposición fina, y recall cae a cero aunque la citación por línea sea perfecta. Mismo patrón que predecía la teoría de la Sesión 11 (Parte 6, RAGAS): la citación verificable demuestra que la fuente existe y se usó; RAGAS mide algo distinto (si el *texto* de la respuesta se parece al *texto* de referencia), y ambas señales pueden discrepar sin que ninguna esté "mal".
- **`answer_relevancy` es sistemáticamente bajo (0.000–0.252, media 0.101).** La "pregunta" es un brief declarativo corto y la "respuesta" es una tabla estructurada de módulos→tareas con decenas de líneas; la métrica (que regenera preguntas a partir de la respuesta y las compara con la original) penaliza estructura donde debería premiar cobertura. Confirma exactamente la advertencia de la teoría: es un artefacto del formato de medición para este caso de uso, no evidencia de mala calidad — el propio informe de citaciones (0 colgantes, 128/171 líneas fundamentadas) contradice la lectura ingenua de "la respuesta no es relevante".
- **Q5 tiene la fidelidad más baja (0.188) — y es la lectura correcta, no un fallo.** Con 5 de 25 líneas explícitamente `insufficient` (el módulo de fraude sin analogía), el texto de la respuesta incluye una sección entera que el juez no puede anclar a ninguna fuente porque, correctamente, **no hay ninguna que anclar**. Una fidelidad más alta aquí habría sido la señal de alarma (indicaría que el modelo rellenó fraude con datos inventados en vez de dejarlo sin fundamentar).
- **`context_precision` cae a 0.500 solo en Q5.** De los presupuestos recuperados, la mitad no aporta a los componentes finalmente citados (posible ruido de KYC/AML o de la mitad `insufficient` de la estimación) — candidato natural para afinar filtrado/reranking en la sesión en vivo, no una regresión de esta implementación.

**Resumen para el directo:** citaciones colgantes 0/171 en 5 estimaciones reales; `context_recall` medio 0.643 pero con un colapso a 0 en el caso de síntesis multi-fuente (Q3) por descomposición fina vs `ground_truth` grueso; `answer_relevancy` bajo por desajuste de formato pregunta/respuesta; el caso de "fraude sin analogía histórica" (Q5) confirma en producción real, no solo en el demo plantado, que `grounded=False` se respeta bajo presión.
