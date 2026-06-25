# Sesión 10 — Resultados de la medición (búsqueda híbrida + reranking)

> Resultados reales del ejercicio (pasos 4-5) ejecutados sobre nuestro stack.
> Documento de ejercicio asociado: [`session-10-exercise-reranking-busqueda-hibrida.md`](session-10-exercise-reranking-busqueda-hibrida.md).
> Fecha de ejecución: **2026-06-25**.

## Cómo se obtuvo

```bash
cd estimator
docker compose up -d                      # Postgres + Redis (la imagen del app crash-loopea: no trae alembic)
DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/estimator' \
  uv run --no-sync alembic upgrade head   # aplica la migración 0003 (content_tsv + GIN) desde el host
uv run --no-sync python -m app.generation.rag.retrieval.verify_reranker   # pre-flight del cross-encoder (OK)
uv run --no-sync python scripts/eval_retrieval_s10.py                      # tabla A/B/C/D
```

- **Corpus base ya ingerido**: 15 presupuestos / 60 chunks (`chunk_type='budget_component'`).
- **Migración 0003**: la columna generada `content_tsv` se rellenó para los 60 chunks existentes al añadirla; índice GIN `ix_chunks_content_tsv` creado.
- **Reranker**: `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (multilingüe), descarga ~450 MB la primera vez, carga ~176 s; pre-flight OK (doc relevante 2,95 vs irrelevante −9,01).
- **Embeddings**: las 5 consultas del golden set se embeben una vez con OpenAI (excluido de las latencias).
- **Método**: precision@5 = chunks del top-5 cuyo `budget_id` está en los relevantes anotados; latencia = mediana de 3 ejecuciones medidas + 1 de calentamiento descartada; umbral de distancia desactivado (2.0) para medir calidad de *ranking*, no el soft-fail.

## Tabla comparativa A/B/C/D

| Config | Búsqueda | Reranking | Precision@5 | Latencia (ms) |
|:------:|:--------:|:---------:|:-----------:|:-------------:|
| **A** | Vectorial | No | **0,96** | **5,4** |
| B | Híbrida | No | 0,96 | 7,6 |
| C | Vectorial | Sí | 0,88 | 106,3 |
| D | Híbrida | Sí | 0,88 | 110,2 |

### Precision@5 por consulta

| Consulta | A | B | C | D |
|---|:---:|:---:|:---:|:---:|
| Q1 — banca móvil (OAuth2 / instant payments / ledger) | 0,80 | 0,80 | 1,00 | 1,00 |
| Q2 — e-commerce storefront (catálogo / checkout / recomendaciones) | 1,00 | 1,00 | 1,00 | 1,00 |
| Q3 — telemedicina (scheduling / vídeo / FHIR) | 1,00 | 1,00 | 1,00 | 1,00 |
| Q4 — IoT industrial (telemetría / mantenimiento predictivo) | 1,00 | 1,00 | 0,80 | 0,80 |
| Q5 — pasarela de pagos (fraude / conciliación / ledger) | 1,00 | 1,00 | 0,60 | 0,60 |

## Conclusiones (paso 5)

**Configuración elegida: A (vectorial, sin reranking).** Es la más barata (5,4 ms) y la más precisa (0,96).

- **El reranking NO compensa aquí — lo empeora**: 0,96 → 0,88, y ~20× más latencia (+100 ms). Ayuda en Q1 (0,80→1,00) pero perjudica Q4 (1,00→0,80) y Q5 (1,00→0,60), empujando un chunk relevante fuera del top-5. Neto negativo.
- **La híbrida no aporta** sobre la vectorial (0,96 = 0,96): las 5 consultas son conceptuales y bien formuladas, así que la rama léxica no rescata nada y RRF degrada con elegancia.
- **Por qué**: corpus pequeño y bien diferenciado (4 sectores nítidos, ~15 proyectos) → la búsqueda vectorial ya ordena casi perfecto, no queda nada que el cross-encoder pueda rescatar. Es el escenario "cuándo NO rerankear" del artículo 1.
- **No contradice la teoría, la confirma**: el reranking paga cuando los relevantes *están* entre los candidatos pero *mal ordenados*; aquí ya están bien ordenados. **Decide el dato, no la moda** — y el dato dice "no" en este corpus. El arnés (`eval_retrieval_s10.py` + golden set) queda en el repo para re-medir cuando el corpus crezca.

## ¿Es nuestro corpus anormalmente pequeño? — comparación con el oficial

No: el del repo oficial es **del mismo tamaño**.

| | `budgets_sample.json` (lo que evalúa el golden set) | `task_corpus.json` (no evaluado) |
|---|---|---|
| **Oficial** | 17 presupuestos / ~60 chunks | 12 proyectos / ~222 chunks |
| **Nuestro** | 15 presupuestos / ~60 chunks | 12 / ~222 (byte-idéntico) |

Ambos golden sets evalúan **solo** `chunk_type='budget_component'` (k=5, 5 consultas, 10 presupuestos relevantes anotados), así que el `task_corpus.json` (chunks `historical_task`, para el *grounding* del flujo `from-transcript`) **no infla** el corpus de la medición en ninguno de los dos. Conclusión: el resultado (reranking marginal/negativo) está **dominado por el tamaño y la separación del corpus**, no por una particularidad de nuestro repo; el profesor, con un corpus equivalente, vería la misma *forma* (sus cifras absolutas diferirían: sus `budget_id` son `BUD-2024-001..017`, los nuestros otros). El reranking brillaría con un corpus mayor o más "confundible" (muchos proyectos del mismo sector con matices), donde la vectorial baja de 0,96 y deja margen que recuperar.
