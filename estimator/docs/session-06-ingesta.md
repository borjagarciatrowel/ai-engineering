# Sesión 6 (en vivo) — Calidad del dato, decisiones de arquitectura e ingesta 🔴

> Este documento cubre el **contenido principal** de la Sesión 6 (los 4 artículos
> del módulo "datos"). El ejercicio *pre-sesión* (stress test del CAG) está en
> [`session-06.md`](session-06.md); aquí empieza el Módulo 3 (RAG) construyendo
> los cimientos: **antes de vectorizar nada**, auditar, parsear, limpiar y
> proteger los datos.

Portado desde el repo oficial del curso (`ai-engineering-oficial`, commit
`session_06_completed`) y **adaptado a nuestro stack** (las divergencias van en
§7). Todo el código nuevo vive en `estimator/app/ingestion/` + `app/persistence/`.

---

## 1. Los cuatro artículos → los cuatro sub-bloques de código

| Artículo (PDF) | Idea | Módulo en `app/ingestion/` |
|---|---|---|
| 1. Calidad del dato y **decisiones de arquitectura** | CAG vs RAG vs híbrido; las 4 restricciones del CAG (ventana, coste, latencia, *lost-in-the-middle*) | `architecture.py` |
| 2. **Auditoría e inventario** de datos | el catálogo de fuentes es *código* versionado, no documentación | `catalog/` + `data/catalog/catalog.yaml` |
| 3. **Pipeline de extracción** multi-formato | contrato canónico `Document`; capas loaders → parsers → normalización | `documents/`, `loaders/`, `parsers/`, `orchestrator.py` |
| 4. **Limpieza, normalización y validación** | pandas para reparar + Pandera como contrato de contenido (valid/cuarentena/descarte) | `cleaning/` |
| (puente del art. 4 → implementado en vivo) | **PII**: pseudonimización reversible antes de vectorizar | `pii/` |

La tesis del módulo: *no amount of clever chunking or fancy architecture can fix
fundamentally bad data*. Por eso se dedican tres artículos a los datos **antes**
de tocar embeddings o base vectorial.

---

## 2. La decisión arquitectónica (`architecture.py`)

CLI puro, no va en el path HTTP. `python -m app.ingestion.architecture` razona
sobre el corpus del Proyecto 2:

```
Recomendación arquitectónica: RAG
```

- `CAGViability` — las 4 restricciones como un `all([...])` (es un **AND**: una en
  rojo mata el CAG).
- `recommend_architecture(corpus, model)` — 4 ejes: volumen vs ventana,
  frecuencia de refresco, trazabilidad, control de acceso. El Proyecto 2 falla
  tres de los cuatro → **RAG** (con capa residual de CAG para lo estable).
- Fine-tuning queda fuera a propósito: es una capa ortogonal (enseña *cómo*
  responder, no añade datos ni resuelve trazabilidad).

## 3. El catálogo como código (`catalog/`)

`data/catalog/catalog.yaml` se carga y valida con Pydantic (`catalog/models.py`).
Tres decisiones por fuente: `include` / `review` / `exclude` (las dos últimas
exigen `decision_reason` — excluir es disciplina, no desidia). El catálogo del
Proyecto 2 trae 3 fuentes: `presupuestos_json` (include), `transcripciones_txt`
(review: un fichero legacy sin tags), `rate_card_xlsx` (exclude: `actuality=1`,
obsoleta). `catalog/inspect.py` produce *facts* (file_count, tamaño,
formats_detected) que fundamentan las decisiones; las opiniones viven en el YAML.

## 4. El contrato canónico `Document` + el pipeline (`documents/`, `loaders/`, `parsers/`, `orchestrator.py`)

- **`Document`** (`documents/models.py`): plano a propósito — `id`, `text`,
  `metadata`. Todo lo específico del formato cae en `metadata.extra`.
- **Loaders** (`loaders/filesystem.py`): resuelven *cómo llego al fichero*
  (bytes), nunca miran dentro.
- **Parsers** (`parsers/`): un `Parser` es un `typing.Protocol`. Solo dos van
  registrados (`default_registry`): `BudgetJsonParser` (JSON → markdown
  estructurado) y `TranscriptTxtParser` (detecta tags `[hh:mm:ss] Speaker:` →
  un doc por turno; legacy → un doc por bloque). **Los parsers XLSX/DOCX/PDF
  viven solo en las `guides/` del profesor — no se portan** (ver §7).
- **Orchestrator** (`orchestrator.py`): catálogo + loader + parser → `list[Document]`,
  respetando la `decision` del catálogo y actualizando la fila `ingestion_jobs`
  (pending → running → completed/failed).

## 5. Limpieza + validación (`cleaning/`)

Dos pasadas separadas a propósito (*cleaning shapes the data, validation
gatekeeps it*):

1. `clean_budget_records` (pandas): nulos disfrazados → `pd.NA`, casing de moneda,
   coerción permisiva de fechas (`dayfirst=True`) y números, **dedup por hash de
   contenido** con regla de negocio explícita (*quédate con el `signed_at` más
   reciente*).
2. `validate_with_policy` (Pandera, `lazy=True`): el schema `BudgetRecord` es
   estricto; los fallos se enrutan a **valid / cuarentena / descarte**. Negativos
   o `budget_id` malformado → descarte; nulos recuperables → cuarentena.

Demo: `uv run python scripts/demo_cleaning_s06.py` sobre el seed real →
**6 ficheros → 5 tras dedup → 3 válidos, 1 cuarentena, 1 descartado** (el
`total_amount: -50000`). Coincide con el guion del artículo 4.

## 6. PII — pseudonimización reversible (`pii/`)

El puente del artículo 4: los `Document` validados todavía llevan PII (nombres,
emails, IDs). Mitigar **antes** de vectorizar.

- `analyzer.py`: Presidio `AnalyzerEngine` cableado a **`es_core_news_md`** (con
  el modelo inglés por defecto, Presidio *silenciosamente* no detecta nombres
  hispanos — el momento didáctico de la sesión).
- `recognizers.py`: reconocedores regex para `BUDGET-YYYY-NNNN` y `CLI-NNNN`.
- `pseudonymizer.py`: `ConsistentPseudonymizer` — **mismo valor → mismo
  pseudónimo** (Faker `es_ES`), siempre, gracias al mapping store. HMAC-SHA256
  del original con salt: a la BD llega el *hash*, nunca el texto → "derecho al
  olvido" (Art. 17) auditable borrando la fila por hash.
- `mapping_store.py`: `PostgresMappingStore` (prod, sobre `MappingsRepository`)
  e `InMemoryMappingStore` (tests/scripts).

Demo: `uv run python scripts/demo_pii_s06.py` (requiere el modelo es, ver §8).

## 7. Divergencias vs el profesor (el patrón recurrente — re-aplicar en cada sync)

Mantenemos el backend alineado pero adaptado a nuestro stack (igual que en
sesión 5). En esta sesión:

1. **Persistencia: 1 solo Postgres + Alembic.** El profesor levanta un **segundo**
   Postgres `pgvector` en el puerto 5433. Nosotros reutilizamos **nuestro único
   Postgres** (`DATABASE_URL`, driver **psycopg2**, servicio `postgres`, 5432).
   `app/persistence/` (engine + `Base` propio + repos) se porta casi literal pero
   apunta a esa misma BD; **Alembic** gestiona solo las 2 tablas nuevas
   (`pseudonym_mappings`, `ingestion_jobs`), mientras las tablas de sesión 5
   (`estimations`, `chat_sessions`) siguen con `app/db.py` `create_all` +
   `_ensure_columns`. **Una BD, dos mecanismos de creación** — convivencia
   deliberada. La imagen sube a `pgvector/pgvector:pg16` (superset drop-in) para
   dejar lista la Sesión 7 (vector extension), pero **no se activa** ninguna
   extensión aquí.
2. **`unstructured[all-docs]` NO se instala.** Los parsers XLSX/DOCX/PDF que lo
   usarían viven solo en las `guides/` del profesor (instructor-only); el propio
   repo oficial no los registra. Nos ahorramos cientos de MB en la imagen.
3. **`alembic upgrade head`** se ejecuta al arrancar el contenedor
   (`docker-compose.yml`, comando del servicio `estimator`).
4. **Frontend Angular** intacto (no portamos el `estimator-web` Rails ni Streamlit).
5. Los cambios que el profesor hizo a `services/estimation.py` /
   `schemas/estimation.py` / `routers/sessions.py` en esta sesión eran la
   **telemetría del stress test** (`TurnObservation`, `attachments_total_chars`),
   que ya teníamos del pre-ejercicio (commit `d9065d2`).

## 8. Cómo se ejecuta

```bash
cd estimator
uv sync                                   # instala pandas, pandera, presidio, spacy, faker, alembic, openpyxl
uv run python -m spacy download es_core_news_md   # modelo es (solo runtime PII; los tests lo stubbean)

# Razonar sobre la arquitectura (CLI)
uv run python -m app.ingestion.architecture

# Inventario factual del corpus
uv run python -m app.ingestion.catalog.inspect data/seed
uv run python -m app.ingestion.catalog.loader data/catalog/catalog.yaml

# Demos de los sub-bloques
uv run python scripts/demo_cleaning_s06.py
uv run python scripts/demo_pii_s06.py

# Pre-flight de la sesión (paquetes, modelo es, catálogo, Postgres+migración)
uv run python scripts/preflight_s06.py

# Endpoint de ingesta (requiere Postgres + alembic upgrade head)
# POST /api/v1/ingestion/runs   {"source_name": "presupuestos_json"}  → 202 + job_id
# GET  /api/v1/ingestion/jobs/{job_id}                                → estado del job
```

## 9. Verificación

- **227 tests verdes** (187 previos + 40 nuevos de ingesta), `ruff` limpio.
- `import app.main` OK (router de ingesta cableado, 19 rutas).
- `architecture` CLI → `RAG`.
- `demo_cleaning` → 3 válidos / 1 cuarentena / 1 descarte sobre el seed real.
- `alembic upgrade head --sql` genera SQL válido para las 2 tablas (offline, sin BD).
- `demo_pii` → Presidio(es) + recognizers + Faker + mapping store, 20 entidades
  pseudonimizadas, consistencia por valor.

Los tests de PII **no** cargan spaCy (stubbean el analyzer); los de limpieza usan
pandas/pandera reales. Funcionan también en pandas 3.0 / pandera 0.31 (más
nuevos que el `>=2.2` / `>=0.20` del profesor).
