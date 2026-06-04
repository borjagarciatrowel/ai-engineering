# Sesión 7 — Pipeline mínimo de embeddings y chunking 🔴

> Este documento describe **solo los cambios del ejercicio previo a la sesión 7**: un
> módulo nuevo `embedding_pipeline/` dentro del servicio IA (`estimator/`) que parte
> presupuestos en *chunks*, los convierte en vectores con OpenAI y los devuelve por HTTP.
> No se toca ni la interfaz Angular ni el backend de negocio. La persistencia en base de
> datos vectorial (pgvector) es deliberadamente de la **Sesión 8**.
>
> Basado en el enunciado oficial, adaptado a los desvíos de esta implementación: el servicio
> se llama `estimator/` (no `servicio_ia/`) y el fichero `data/budgets_sample.json` **no se
> proporcionó**, así que se ha creado uno propio respetando el esquema indicado. Las
> divergencias se señalan a lo largo del texto.

---

## 0. Explicación para cualquiera (sin tecnicismos)

Imagina que tienes una caja de **presupuestos antiguos** de proyectos de software. Cada
presupuesto tiene un resumen del proyecto y una lista de *componentes* ("backend de login",
"pasarela de pagos", "panel de administración"…), cada uno con su descripción, su tecnología
y sus horas.

Queremos, más adelante, poder **buscar por significado**: "enséñame presupuestos parecidos a
*autenticación con OAuth para banca*", aunque las palabras exactas no coincidan. Para eso, un
ordenador necesita convertir cada texto en una lista de números que captura *de qué trata* —
eso es un **embedding**. Dos textos que hablan de lo mismo tienen listas de números
parecidas; dos textos sin relación, listas distintas.

Pero no se puede meter un presupuesto entero de golpe: hay que **trocearlo** en pedazos con
sentido. A trocear se le llama *chunking*. Aquí la regla es sencilla y deliberada: **un
componente del presupuesto = un trozo**. Y a cada trozo le pegamos delante una "cabecera de
contexto" (a qué proyecto, sector y año pertenece) para que no pierda el hilo.

Este ejercicio construye esa **cadena de montaje mínima**:

1. **Entra** un presupuesto en JSON.
2. Se **trocea** por componentes (con su cabecera de contexto).
3. Cada trozo se **convierte en vector** (embedding) llamando a OpenAI.
4. **Salen** los vectores por una API web, junto con unas estadísticas (cuántos trozos,
   cuántos *tokens*, cuánto costaría en dólares).

Y se cierra con un pequeño programa de línea de comandos (`compare.py`) que coge **dos
frases**, las convierte en vectores y dice **cómo de parecidas** son (un número entre 0 y 1).
Es el "test de humo": si dos frases que significan lo mismo dan un número alto, y dos que no
tienen nada que ver dan un número bajo, sabemos que los embeddings funcionan.

> ⚠️ **Una nota honesta:** la parte 4 (los números reales de similitud) quedó **pendiente**
> porque la clave de OpenAI del `.env` está sin saldo (`429 insufficient_quota`). El código
> funciona de punta a punta —se ha verificado el troceo, la validación y la ruta web—, pero
> los tres números del *test de humo* hay que sacarlos con una clave con crédito. Una sola
> orden los rellena (ver §10).

---

## 1. Objetivo

Construir dentro del servicio IA un pipeline funcional mínimo que reciba presupuestos
históricos en JSON, los parta en *chunks* respetando la estructura del documento, genere
embeddings con OpenAI (`text-embedding-3-small`) y devuelva los vectores listos para uso
posterior. Se cierra con un script CLI que verifica que los embeddings discriminan bien
comparando la similitud coseno entre tres parejas de textos.

El producto **no se persiste todavía**: los vectores se generan en memoria y se devuelven por
HTTP. La persistencia (PostgreSQL + pgvector) entra en la Sesión 8.

## 2. Qué entra y qué no entra

**Entra:** chunker estructural para presupuestos JSON (un componente = un chunk); embedder
que invoca `text-embedding-3-small`; endpoint `POST /embeddings/ingest`; script CLI
`compare.py` (similitud coseno); validación con tres parejas de textos.

**No entra (se ve en directo):** otras estrategias de chunking (recursive, semantic,
hierarchical, late chunking, contextual retrieval); comparativa entre modelos de embeddings;
enriquecimiento del chunk con contexto generado por LLM; persistencia en BD vectorial;
búsqueda semántica (retrieval); métricas formales (recall@k, NDCG…); cambios en la interfaz
o el backend de negocio.

## 3. Estructura del módulo

```
estimator/
├── app/
│   ├── embedding_pipeline/        ← NUEVO
│   │   ├── __init__.py            ← re-exporta las clases públicas
│   │   ├── schemas.py             ← modelos Pydantic v2
│   │   ├── chunker.py             ← JSONStructuralChunker
│   │   ├── embedder.py            ← OpenAIEmbedder
│   │   ├── router.py              ← POST /embeddings/ingest
│   │   └── SANITY_CHECK.md        ← resultados de las 3 parejas
│   ├── dependencies.py            ← + get_openai_embedder()
│   └── main.py                    ← + include_router(embeddings.router)
├── scripts/
│   └── compare.py                 ← NUEVO (CLI similitud coseno)
├── data/
│   └── budgets_sample.json        ← NUEVO (15 presupuestos, creado a mano)
└── pyproject.toml                 ← + tiktoken
```

> **Desvío de nomenclatura.** El enunciado coloca el módulo en `servicio_ia/app/`. En esta
> implementación el servicio IA es `estimator/`, así que el módulo vive en
> `estimator/app/embedding_pipeline/`. Misma estructura interna.

## 4. Decisiones de diseño

### 4.1 Chunking estructural: un componente = un chunk

`JSONStructuralChunker.chunk(budgets)` itera presupuestos y, por cada `BudgetComponent`,
produce un `Chunk`. **No** hay overlap ni *fixed-size splitting* de descripciones largas: se
confía en la estructura del JSON. Un componente cabe holgadamente como chunk individual (en
el sample, los chunks miden **67–104 tokens**). Si una descripción fuese excepcionalmente
larga, eso es un dato a discutir en directo, no algo que partir a ciegas.

### 4.2 Cabecera de contexto (contextual chunk header)

El `text` que se embebe **no** es solo la descripción del componente: lleva delante el
contexto del presupuesto padre.

```
[Project: {project_summary}]
[Client sector: {sector} | Year: {year} | Main tech: {main_technology}]

Component: {name}
Description: {description}
Tech stack: {tech_stack join ", "}
Complexity: {complexity}
Estimated hours: {estimated_hours}
```

La decisión de *prepender* el contexto es deliberada: sin ella, un componente
"Authentication backend" perdería la pista de a qué cliente y sector pertenece, y los
embeddings de descripciones sueltas colapsarían entre proyectos muy distintos. Conecta con el
concepto de *contextual chunk headers* del material asíncrono.

### 4.3 `token_count` con el mismo modelo que embebe

Se cuenta con `tiktoken.encoding_for_model("text-embedding-3-small")`. Contar con el *mismo*
tokenizador que luego embebe permite detectar chunks anormalmente grandes **antes** de pagar
la llamada a la API. La codificación se cachea con `lru_cache`.

### 4.4 Embedder: batches, reintentos y coste

- **Batches:** `embed_many` llama a `embeddings.create` con **listas** de hasta 100 chunks
  por petición (el endpoint acepta listas), no una llamada por chunk. En el sample son 60
  chunks → 1 sola llamada, pero la lógica de troceo en lotes está y se loguea por lote.
- **Reintentos:** `RateLimitError` se reintenta con backoff exponencial simple (1s, 2s, 4s),
  3 reintentos; cualquier otro error se propaga hacia arriba.
- **Observabilidad:** cada lote se loguea con `structlog` (`embeddings_batch_processed`:
  nº de chunks, tokens, latencia), alineado con la convención de la Sesión 3.
- **Coste:** `estimated_cost_usd = total_tokens / 1e6 * PRICE_PER_MILLION_TOKENS_USD`, con la
  constante de módulo `PRICE_PER_MILLION_TOKENS_USD = 0.02` ($0.02 por millón de tokens de
  entrada de `text-embedding-3-small`), claramente etiquetada porque cambia con el tiempo.
- **Dimensión por defecto (1536):** no se fuerza dimensión menor; la discusión sobre
  Matryoshka es del directo.

### 4.5 Ruta `POST /embeddings/ingest` (desvío del prefijo `/api/v1`)

El resto de routers del proyecto usan prefijo `/api/v1/...`. Aquí se respeta **literalmente**
el enunciado: la ruta completa queda `POST /embeddings/ingest` (prefijo `/embeddings`). Es un
desvío consciente de la convención del proyecto para cumplir el entregable tal cual se pide y
que la ruta aparezca exactamente así en `/docs`.

### 4.6 Sin numpy ni scikit-learn

La similitud coseno de `compare.py` se calcula a mano (producto escalar / producto de normas)
con la biblioteca estándar. No se añaden librerías pesadas solo para eso.

## 5. Modelos de datos (`schemas.py`, Pydantic v2)

- **`ClientMetadata`** — `name`, `sector`, `country`.
- **`BudgetComponent`** — `component_id`, `name`, `description`, `tech_stack: list[str]`,
  `estimated_hours: int`, `complexity`, `dependencies: list[str]`.
- **`Budget`** — `budget_id`, `client_metadata`, `project_summary`, `main_technology`,
  `year`, `total_estimated_hours`, `components: list[BudgetComponent]` (≥ 1).
- **`Chunk`** — `chunk_id`, `text`, `metadata: dict`, `token_count: int`.
- **`EmbeddedChunk`** — extiende `Chunk` con `embedding: list[float]`.
- **`IngestRequest`** — `budgets: list[Budget]` (≥ 1, `extra="forbid"`).
- **`IngestResponse`** — `chunks: list[EmbeddedChunk]` + `stats`.
- **`IngestStats`** — `total_budgets`, `total_chunks`, `total_tokens`, `estimated_cost_usd`.

> **Validadores explícitos donde tiene sentido.** `complexity` es un `Literal["low",
> "medium", "high"]` (universo cerrado y conocido). `sector`, `country` y `main_technology`
> se dejan como `str` abierto a propósito: su universo no es fijo y un `Literal` rechazaría
> datos futuros válidos. El enunciado describe `stats` como un dict; aquí es un modelo
> `IngestStats` tipado (más explícito, serializa igual).

## 6. El chunker (`chunker.py`)

`chunk_id` con formato `{budget_id}::{component_id}` (p. ej. `BUD-2024-014::AUTH-001`) para
que sea trazable. La `metadata` que viaja con el chunk —pero **no** se embebe— incluye:
`budget_id`, `component_id`, `client_sector`, `main_technology`, `year`, `complexity`,
`estimated_hours`. Son los campos filtrables para futuras consultas (Sesión 8).

## 7. El embedder (`embedder.py`)

Clase `OpenAIEmbedder` con dos métodos públicos:

- `embed_one(text: str) -> list[float]` — un texto, su vector (lo usa `compare.py`).
- `embed_many(chunks: list[Chunk]) -> list[EmbeddedChunk]` — en lotes, preservando el orden
  de entrada (se ordena la respuesta por `index` por si la API la devuelve desordenada).

Recibe el cliente `OpenAI` por inyección (se reutiliza el `get_openai_client()` ya existente
de la Sesión 4), de modo que no se crea un segundo cliente.

## 8. El endpoint (`router.py`)

`POST /embeddings/ingest`. El handler es un orquestador fino:

```
chunker.chunk(budgets) -> embedder.embed_many(chunks) -> IngestResponse
```

Códigos de estado: **200** éxito; **422** validación Pydantic (lo gestiona FastAPI); **500**
error no controlado de la API de embeddings (mensaje genérico al cliente, detalle en los
logs); **503** si no hay `OPENAI_API_KEY` configurada (los embeddings no tienen fallback
offline). El embedder se inyecta vía `get_openai_embedder()` en `app/dependencies.py`. El
router se registra en `app/main.py`. Verificable en `/docs` (Swagger UI).

## 9. `compare.py` — similitud coseno (`scripts/compare.py`)

CLI con `argparse` (`--text-a`, `--text-b`). Reutiliza `OpenAIEmbedder`. Coseno a mano. Se
puede ejecutar de dos formas (ambas documentadas en el README):

```bash
# Dentro del contenedor
docker compose exec estimator python scripts/compare.py --text-a "..." --text-b "..."

# Fuera del contenedor (con estimator/.env cargado y una OPENAI_API_KEY con saldo)
uv run python scripts/compare.py --text-a "..." --text-b "..."
```

Salida (formato libre):

```
Text A: ...
Text B: ...
Cosine similarity: 0.8421
```

## 10. Validación con tres parejas (`SANITY_CHECK.md`)

Se ejecuta `compare.py` sobre exactamente tres parejas y se guardan los resultados en
[`app/embedding_pipeline/SANITY_CHECK.md`](../app/embedding_pipeline/SANITY_CHECK.md):

- **Pareja A — cercanas** (esperado alto, ≳ 0.6): OAuth/JWT fintech ↔ "Authorization service
  using JSON Web Tokens for a banking application".
- **Pareja B — no relacionadas** (esperado bajo, ≲ 0.4): la misma de OAuth ↔ "Database
  migration from MySQL to PostgreSQL with zero downtime".
- **Pareja C — genéricas/ambiguas** (sin expectativa fija): "Backend services" ↔
  "API development".

> **Estado:** los tres números quedan **pendientes**. La clave de OpenAI del `.env` devuelve
> `429 insufficient_quota`, así que la API rechaza la petición antes de generar el vector.
> Curiosamente, este mismo error **ejercitó el camino de reintentos** del embedder (3
> backoffs y re-lanzado). Para rellenar la tabla: apuntar `.env` a una `OPENAI_API_KEY` con
> saldo y relanzar las tres órdenes (están en `SANITY_CHECK.md`). El comentario sobre la
> expectativa (A > C > B, o como mínimo A ≫ B) ya está escrito.

## 11. Datos de ejemplo (`data/budgets_sample.json`)

El enunciado dice que el fichero se proporciona en el repo de datos del programa, pero **no
se entregó**. Se ha creado uno propio respetando el esquema: **15 presupuestos** normalizados
que cubren cuatro sectores (`fintech`, `e-commerce`, `healthcare`, `industrial`) y stacks
variados (`ruby_on_rails`, `nextjs`, `django`, `spring_boot`, `go`, `laravel`, `nodejs`,
`dotnet`, `fastapi`, `react_native`, `flutter`, `python`). Cada presupuesto tiene 4
componentes con `dependencies` cruzadas realistas → **60 chunks** en total. La variedad es
deliberada: hace que el sanity check y, en la Sesión 8, el retrieval, tengan señal con la que
discriminar.

## 12. Dependencias (`pyproject.toml`)

`openai` ya estaba desde la Sesión 1. Se añade `tiktoken>=0.7.0`. **No** se añaden `numpy`
ni `scikit-learn`. Reconstruir si se usa Docker: `docker compose build estimator`. En local:
`uv sync` (instala `tiktoken 0.12.0`).

## 13. Verificación

```bash
cd estimator

# Parseo + chunker sobre el sample (sin red): 15 presupuestos → 60 chunks
uv run python -c "import json; from app.embedding_pipeline import JSONStructuralChunker, Budget; \
b=[Budget(**x) for x in json.load(open('data/budgets_sample.json'))]; \
print(len(b), 'budgets', len(JSONStructuralChunker().chunk(b)), 'chunks')"

# La app arranca y la ruta queda registrada
uv run python -c "from app.main import app; \
assert '/embeddings/ingest' in [r.path for r in app.routes]; print('route OK')"
```

Resultado obtenido: `15 budgets 60 chunks` y `route OK`. La generación real de vectores y el
sanity check numérico requieren una `OPENAI_API_KEY` con saldo (ver §10).

## 14. Entregable

- ✅ Módulo `embedding_pipeline/` completo (`chunker.py`, `embedder.py`, `schemas.py`,
  `router.py`, `__init__.py`).
- ✅ Script `scripts/compare.py` funcional.
- ✅ Endpoint `POST /embeddings/ingest` registrado y accesible desde `/docs`.
- ✅ `SANITY_CHECK.md` con las tres parejas y el comentario (números pendientes de clave con
  saldo).
- ✅ README actualizado (cómo invocar el endpoint, cómo correr `compare.py` dentro y fuera
  del contenedor).
- ✅ `pyproject.toml` actualizado (`tiktoken`).
- ✅ `data/budgets_sample.json` creado (no se proporcionó).

> Los tests automatizados se difieren a una sesión posterior (no son requisito del ejercicio).
