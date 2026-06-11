# Sesión 8 — Persistencia en pgvector + endpoint de búsqueda semántica

> Este documento cubre el **ejercicio previo a la Sesión 8**: persistir el pipeline de
> embeddings construido en la Sesión 7 en **PostgreSQL + pgvector** y exponer un endpoint de
> **búsqueda semántica** sobre los presupuestos históricos.
>
> El código está **basado íntegramente en la solución del profesor** (repo oficial,
> `app/generation/rag/store/`, `ingest_service.py`, `retriever.py`, `api/search.py`,
> migración `0002`), adaptado a las **divergencias** que ya arrastraba nuestro proyecto
> (un solo Postgres compartido, persistencia de conversaciones en BD, *records*
> y telemetría propias). Todas las divergencias se señalan a lo largo del texto y se
> resumen en el §13.
>
> Lo que **no** se toca: la interfaz Angular, el backend de negocio, ni nuestra
> persistencia de conversaciones (`DbSessionStore`). La Sesión 8 sólo **añade** la
> persistencia de documentos/chunks; no sustituye la memoria conversacional.

---

## 0. Explicación para cualquiera (sin tecnicismos)

En la Sesión 7 enseñamos al programa a leer **presupuestos antiguos**, trocearlos en pedazos
con sentido (un pedazo por "componente": *backend de login*, *pasarela de pagos*…) y convertir
cada pedazo en una **lista de números que captura su significado** (un *embedding*). Pero esos
números se calculaban y se devolvían al instante: **no se guardaban en ningún sitio**. Apagabas
el programa y se perdían.

La Sesión 8 arregla justo eso. Ahora:

1. **Guardamos los presupuestos en una base de datos** preparada para entender esas listas de
   números (PostgreSQL con una extensión llamada *pgvector*). Cada presupuesto se guarda como un
   **documento**, y cada uno de sus pedazos como un **chunk** con su lista de números al lado.
   Todo el guardado de un presupuesto ocurre **de golpe** (una sola operación): si algo falla a
   mitad, no queda nada a medias.

2. **Podemos buscar por significado.** Le preguntas en lenguaje natural —"servicio backend
   seguro con control de acceso por tokens para banca"— y el programa devuelve los pedazos de
   presupuesto **más parecidos en significado**, aunque no compartan ni una palabra con tu
   pregunta. Para decidir "parecido" mide la **distancia** entre las listas de números: cuanto
   menor, más se parecen.

Una analogía: imagina una biblioteca enorme donde cada párrafo tiene una **coordenada** según
de qué trata. Guardar = colocar cada párrafo en su coordenada. Buscar = ir a la coordenada de tu
pregunta y coger los párrafos más cercanos. De momento el bibliotecario **recorre todas las
estanterías** una a una (es rápido porque hay pocos libros); en la sesión en directo le daremos
un "índice" para que vaya directo, y mediremos cuánto mejora.

Tres detalles que decidimos a propósito y que conviene entender:

- **Dos cajones, no uno.** Los datos del presupuesto (de quién es, de qué año) van en un cajón
  (`documents`); los pedazos van en otro (`chunks`). Así no repetimos lo mismo cien veces y, si
  borras un presupuesto, sus pedazos se borran solos.
- **Una "ficha flexible" para los datos sueltos.** Lo que siempre está (tipo, fecha) va en
  columnas fijas; lo que el troceador añade y puede cambiar (sector, tecnologías, horas) va en
  una ficha flexible (JSONB) que se puede consultar sin rehacer la base de datos cada vez.
- **Todavía sin "índice" de búsqueda.** A propósito. Queremos medir primero lo lento/rápido que
  es **sin** el truco, para luego ver cuánto ayuda el truco en directo.

El resto del documento explica cada pieza, primero el *qué* y luego el detalle técnico.

---

## 1. Objetivo y alcance

**Objetivo:** persistir el pipeline de la Sesión 7 en PostgreSQL + pgvector y exponer un endpoint
de búsqueda semántica funcional sobre los presupuestos históricos. Al terminar, el servicio IA:

1. Levanta un Postgres con `pgvector` como dependencia declarada (ya lo teníamos: imagen
   `pgvector/pgvector:pg16`).
2. Tiene un esquema relacional propio (tablas `documents` y `chunks`) gestionado con migraciones
   Alembic.
3. Persiste cada presupuesto ingerido como un `document` con sus `chunks` (cada uno con su
   embedding) **en una sola transacción**.
4. Resuelve una query semántica vía SQL devolviendo los *k* chunks más cercanos por **distancia
   coseno**.

**Lo que NO se hace en este ejercicio** (es material del directo, deliberadamente fuera de
alcance):

- **Índices vectoriales** (HNSW, IVFFlat). El *sequential scan* es la línea base contra la que se
  medirá el índice en directo.
- **Filtros por metadata** (`WHERE chunk_type = …`, `WHERE metadata->>'sector' = …`).
- **Búsqueda híbrida** (full-text + vector).
- **Tuning de parámetros** (`shared_buffers`, `maintenance_work_mem`, `ef_search`). Defaults.

---

## 2. El stack y las dependencias nuevas

Al `pyproject.toml` del servicio IA se añaden:

```toml
"asyncpg>=0.29",   # driver async que recomienda SQLAlchemy 2.0 para el camino caliente
"pgvector>=0.3",   # registra el tipo `vector` y los operadores de distancia en el ORM
"greenlet>=3.0",   # el motor async de SQLAlchemy lo necesita (puente sync↔async)
```

`asyncpg` es el driver asíncrono que SQLAlchemy 2.0 recomienda para Postgres. `pgvector` (el
paquete Python) registra el tipo `vector` en SQLAlchemy y expone los operadores de distancia
(`l2_distance`, `cosine_distance`, `max_inner_product`) como métodos invocables desde el ORM.

> **Alineado con el profesor.** Usamos su mismo driver síncrono `psycopg[binary]` (psycopg v3)
> para Alembic y los repositorios de la Sesión 6 — migrado desde `psycopg2-binary`, que
> arrastrábamos de las Sesiones 5–6. `greenlet` no aparece en el enunciado pero es
> **imprescindible**: el motor `async` de SQLAlchemy lo usa internamente; sin él, la primera
> llamada async lanza `ValueError: the greenlet library is required to use this function`.

---

## 3. Paso 1 — Postgres con pgvector (docker-compose)

El enunciado pide añadir un servicio `postgres` con la imagen oficial de pgvector. **Ya lo
teníamos** desde la Sesión 6: nuestro `docker-compose.yml` usa `pgvector/pgvector:pg16` (Postgres
16 con la extensión `vector` precompilada), con `healthcheck` y el servicio `estimator` esperando
a `postgres: condition: service_healthy`. El contenedor aplica `alembic upgrade head` al arrancar.

```yaml
postgres:
  image: pgvector/pgvector:pg16
  environment: { POSTGRES_USER: postgres, POSTGRES_PASSWORD: postgres, POSTGRES_DB: estimator }
  ports: ["5432:5432"]
  healthcheck: { test: ["CMD-SHELL", "pg_isready -U postgres -d estimator"], ... }
```

> **Divergencia.** El profesor declara **dos** Postgres (uno `pgvector` en el puerto 5433 para
> FastAPI y otro para Rails). Nosotros mantenemos **un solo** Postgres en el 5432, compartido por
> toda la persistencia (conversaciones, mappings/jobs de la Sesión 6 y ahora documents/chunks).
> La extensión `vector` no se activaba aún; ahora la activa la migración `0002`.

---

## 4. Paso 2 — Alembic reconoce el tipo `vector`

`alembic/env.py` se ajusta para dos cosas:

```python
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql.base import ischema_names

from app.foundation.persistence.models import Base          # tablas Sesión 6
import app.generation.rag.store.models                       # registra documents/chunks en Base.metadata

config.set_main_option("sqlalchemy.url", get_settings().DATABASE_URL)
ischema_names["vector"] = Vector                             # enseña a la reflexión el tipo vector
target_metadata = Base.metadata
```

- Lee la URL de conexión desde `app.config.Settings.DATABASE_URL` (no de `alembic.ini`), para que
  contenedor, host y CI usen la misma fuente de verdad.
- **Registra el tipo `vector`** en `ischema_names`. Sin esto, `alembic check` / autogenerate
  contra una BD que ya tiene columnas `vector` no sabe mapearlas y produce diffs inconsistentes.
- **Importa `app.generation.rag.store.models`** para que las tablas de la Sesión 8 queden
  registradas en `Base.metadata` (comparten `Base` con las tablas de la Sesión 6).

> **Bug preexistente corregido.** Nuestro `env.py` importaba `from app.persistence.models import
> Base`, una ruta **obsoleta** desde la reorganización por capas de la Sesión 7. La ruta correcta
> es `app.foundation.persistence.models`. Estaba latente porque Alembic no se ejecuta en los tests.

---

## 5. Paso 3 — El esquema: dos tablas (`alembic/versions/0002_session8_pgvector.py`)

La migración `0002` (cadena `0001_session6_initial → 0002_session8_pgvector`) crea la extensión y
las dos tablas:

```python
def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")      # antes de cualquier columna Vector

    op.create_table("documents",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source_path", sa.Text, nullable=False),
        sa.Column("document_type", sa.String(50), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("metadata", postgresql.JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.create_index("ix_documents_source_path", "documents", ["source_path"])

    op.create_table("chunks",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("document_id", sa.BigInteger, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_type", sa.String(50), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedding", Vector(1536), nullable=True),  # nullable a propósito (ver §6)
        sa.Column("metadata", postgresql.JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.create_index("ix_chunks_chunk_type", "chunks", ["chunk_type"])
    op.create_index("ix_chunks_metadata_gin", "chunks", ["metadata"], postgresql_using="gin")
```

Se ejecuta con `docker compose run --rm estimator alembic upgrade head` (o `uv run alembic upgrade
head` en el host). **No hay índice vectorial** (ver §6.4). `down_revision` apunta a nuestra
migración de la Sesión 6, así que la cadena queda `0001 → 0002`.

---

## 6. Las cuatro decisiones de diseño (las que hay que defender)

Estas son las cuatro justificaciones que pide el entregable; también van resumidas en el README.

### 6.1 Dos tablas en vez de una

Un presupuesto produce N chunks. Una sola tabla con la metadata del documento **duplicada en cada
fila** pierde integridad referencial y duplica datos. Con dos tablas y `ON DELETE CASCADE`,
eliminar un presupuesto elimina automáticamente todos sus chunks: **integridad referencial en vez
de duplicación denormalizada**. Es un uno-a-muchos de libro.

### 6.2 `metadata` como JSONB en ambas tablas

Metadata **estable** (tipo de documento, tipo de chunk, fechas) → columnas tipadas. Metadata
**variable** o que el chunker puede enriquecer (sector, tecnologías mencionadas, horas, scope) →
JSONB. El índice **GIN** sobre el JSONB permite consultar por claves arbitrarias
(`metadata->>'client_sector' = 'fintech'`) **sin migrar el esquema cada vez** que aparece una
clave nueva. Estabilidad donde importa, flexibilidad donde el vocabulario aún se mueve.

### 6.3 `cosine_distance` (operador `<=>`) y no L2 ni inner product

Los embeddings de OpenAI están **normalizados**, así que `cosine_distance` e `inner_product`
darían el mismo ranking. Elegimos coseno por dos motivos: (1) es la convención más común en la
literatura RAG; (2) cuando en directo añadamos el índice HNSW con `vector_cosine_ops`, el operador
de la query y la *operator class* del índice estarán **alineados**. Esta alineación es crítica: si
la query usa un operador y el índice está construido con otra operator class, **Postgres ignora el
índice silenciosamente** y cae a sequential scan sin avisar.

### 6.4 Sin índice vectorial, deliberadamente

La migración crea los índices relacionales (FK, `chunk_type`, GIN sobre metadata) pero **ningún
HNSW/IVFFlat**. El sequential scan es la **línea base** contra la que el directo medirá el impacto
del índice. Para el volumen del corpus de ejemplo (decenas de documentos, decenas de chunks) eso
es perfectamente aceptable y el endpoint responde en pocos cientos de ms. Observar esa latencia
*sin* índice es justamente uno de los puntos de partida del directo.

### 6.5 `embedding` nullable, `Vector(1536)` hardcodeado

Dos micro-decisiones del esquema:

- `embedding` es **nullable**: permite insertar un chunk y rellenar el vector después (ingesta
  asíncrona de sesiones futuras). En la Sesión 8 siempre insertamos chunk+vector atómicamente, así
  que ese camino no se ejercita, pero deja la puerta abierta.
- `Vector(1536)` está fijo a la dimensionalidad de `text-embedding-3-small`. Cambiarlo implica
  re-embeber todo el corpus, así que **no es configuración**, es una constante del esquema.

---

## 7. La capa de datos asíncrona (`foundation/persistence/database.py`)

Conviven **dos stacks** a propósito:

- **Síncrono (psycopg v3):** los caminos de la Sesión 6 (mappings, jobs). No están en el camino
  caliente de petición (corren como BackgroundTasks o operaciones puntuales), así que cambiamos
  ergonomía async por simplicidad.
- **Asíncrono (asyncpg):** el store RAG de la Sesión 8 (`POST /embeddings/ingest` y
  `POST /search`). Esos endpoints **sí** están en el camino de petición en tiempo real, así que
  usan el motor async y nunca bloquean el *event loop* en la E/S de Postgres.

Ambos motores leen el mismo `Settings.DATABASE_URL`; el async **intercambia el token del driver**
(misma lógica que el profesor, ya que compartimos el driver síncrono `psycopg`):

```python
def _async_database_url() -> str:
    url = get_settings().DATABASE_URL
    if "+psycopg" in url:
        return url.replace("+psycopg", "+asyncpg")
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url
```

> **Nota.** Al **alinear** el driver síncrono en `psycopg` (v3) —migrado desde `psycopg2` en esta
> sesión, ver §13— el swap queda **idéntico al del repo oficial**. Verificado:
> `postgresql+psycopg://…` → `postgresql+asyncpg://…`.

El factory `get_async_session_factory()` usa `expire_on_commit=False` para que los objetos ORM
(p. ej. el id del documento recién persistido) sigan siendo legibles tras el commit.

---

## 8. El store: modelos ORM + repositorio (`generation/rag/store/`)

### `store/models.py` — las dos tablas como ORM

`DocumentRow` y `ChunkRow`. Detalle de SQLAlchemy a recordar: `metadata` es un atributo
**reservado** en los modelos declarativos, así que el atributo Python es `metadata_` mapeado a la
columna `"metadata"`. La relación lleva `cascade="all, delete-orphan", passive_deletes=True` para
que el `ON DELETE CASCADE` de la BD y el ORM estén de acuerdo.

### `store/repository.py` — `ChunkStore` (acceso a datos async)

El store **nunca abre ni cierra sesiones**: el llamador (servicio de ingesta o retriever) es dueño
de la `AsyncSession`, de modo que una ingesta completa —comprobar duplicado, fila de documento,
filas de chunks— cabe en **una sola transacción**. Tres operaciones:

- `find_document_id(session, source_path)` → respalda el guard de duplicado (409).
- `persist_document_with_chunks(...)` → inserta el documento, hace `flush()` para obtener su `id`
  (sin commit), y añade todos los chunks con `add_all`. **No hace commit**: lo decide el llamador.
- `search(session, query_vector, k)` → los *k* chunks más cercanos por
  `ChunkRow.embedding.cosine_distance(query_vector)` (operador `<=>`), ordenados ascendente y
  limitados a *k*. Sequential scan.

---

## 9. El servicio de ingesta: una sola transacción (`generation/rag/ingest_service.py`)

`RagIngestService.ingest(...)` orquesta chunk → embed → persist dentro de **una sola sesión async**:

```python
async with self._session_factory() as session, session.begin():
    existing_id = await self._store.find_document_id(session, source_path)   # 1. guard duplicado
    if existing_id is not None:
        raise DuplicateDocumentError(existing_id)
    chunks = self._chunker.chunk([budget])                                   # 2. chunking estructural
    embedded = await asyncio.to_thread(self._embedder.embed_many, chunks)    # 3. embedding por lotes
    document_id = await self._store.persist_document_with_chunks(...)        # 4. documento + chunks
    # 5. commit al salir del `session.begin()`
```

Dos puntos de diseño:

- **El cliente de OpenAI es síncrono** → se ejecuta con `asyncio.to_thread` para no bloquear el
  event loop mientras se calculan los embeddings.
- **La transacción única es el punto clave:** el documento se inserta primero (para que los chunks
  puedan referenciarlo vía `flush`), pero si la API de embeddings falla después, **toda la
  transacción hace rollback** y no queda ningún documento huérfano sin chunks.

`embed_many` hace una única llamada `embeddings.create` por lote (≤100 chunks) — no chunk a chunk.

---

## 10. El endpoint `POST /embeddings/ingest` (refactor) y el 409

El contrato cambió respecto a la Sesión 7: ya **no** devuelve chunks+vectores por HTTP, sino que
los **persiste** y devuelve sólo identificadores y métricas.

- **Request:** `{ "source_path": "...", "document_type": "historical_budget", "content": { …budget… } }`
- **Response 200:** `{ "document_id", "chunks_created", "embedding_dimension", "ingestion_time_ms" }`
- **Response 409** (documento ya existente con ese `source_path`):
  `{ "detail": "Document already ingested", "document_id": 42 }`

El router es fino: mapea excepciones a códigos HTTP. El 409 se devuelve como `JSONResponse`
(no `HTTPException`) para respetar la **forma literal de nivel superior** del enunciado
(`detail` + `document_id` arriba, no anidado). Un `content` malformado falla con 422 *antes* de
tocar la BD o la API de embeddings, gracias a la validación Pydantic de `Budget`.

> El endpoint `POST /embeddings/compare` (laboratorio de chunking de la Sesión 7) se mantiene
> intacto.

---

## 11. El retriever + endpoint `POST /search`

`SemanticRetriever.search(query, k)` (`generation/rag/retriever.py`):

1. Embebe la query con **el mismo modelo** usado en la ingesta (`text-embedding-3-small`) — mezclar
   modelos de embedding haría las distancias incomparables. Cliente síncrono → `asyncio.to_thread`.
2. Pide al `ChunkStore` los *k* chunks más cercanos por coseno.
3. Devuelve un `SearchResponse` con `query`, `k`, `search_time_ms` y `results` (cada `SearchHit`
   con `chunk_id`, `document_id`, `chunk_type`, `content`, `distance`, `metadata`).

El router `POST /search` (`api/search.py`) es fino: las cotas de `k` viven en `SearchRequest`
(`1 ≤ k ≤ 50` → 422 antes de cualquier E/S), y un **corpus vacío es un 200 con `results: []`**, no
un error.

---

## 12. El script `query_examples.py` y `output_examples.txt`

`scripts/query_examples.py` sustituye el rol del antiguo `compare.py` (que medía similitud entre
dos textos sueltos). Ejercita el camino real de extremo a extremo —HTTP contra
`POST /embeddings/ingest` y `POST /search`— con **cinco queries** que prueban el corpus desde
ángulos distintos: componente directo conocido (sanity), reformulación semántica, dominio distinto
(fuera de corpus), consulta ambigua, y consulta muy específica.

Es **idempotente**: primero ingiere `data/budgets_sample.json` (un documento por presupuesto); los
ya persistidos responden 409 y se saltan, así que re-ejecutarlo nunca duplica datos.

```bash
docker compose up -d
docker compose run --rm estimator python scripts/query_examples.py | tee output_examples.txt
```

**Resultado real** (`output_examples.txt`, sobre nuestros 15 presupuestos de ejemplo). Dos
extractos que muestran que los embeddings capturan significado:

```
[1/5] Componente directo conocido (sanity check)
    query: "REST API development with JWT authentication for financial sector"
    chunk_id  distance  chunk_type          content
           1    0.3985  budget_component    [Project: Mobile banking API with OAuth 2.0 authentication ...] sector: fintech
           4    0.4717  budget_component    [Project: Mobile banking API ...]
           ...

[5/5] Consulta muy específica (vocabulario técnico preciso)
    query: "migration from monolith to microservices architecture using Kubernetes"
    chunk_id  distance  chunk_type          content
          53    0.3707  budget_component    [Project: Migration of a monolithic marketplace to microservices ...]
          56    0.4411  budget_component    [Project: Migration of a monolithic marketplace to microservices ...]
```

La query de "dominio distinto" (reservas de restaurante) devuelve distancias claramente más altas
(~0.59+) y resultados sin un match dominante — exactamente lo esperado para algo que no está en el
corpus.

> Nuestro `output_examples.txt` parte de **15** presupuestos (el del profesor, 17). El contenido y
> los `chunk_id` difieren porque el corpus de ejemplo es el nuestro.

---

## 13. Divergencias respecto al repo oficial del profesor

Todo lo demás (modelos, repositorio, servicio de ingesta, retriever, endpoints, migración, tests)
es **igual** que la solución del profesor. Las diferencias son las que ya arrastraba el proyecto:

| # | Profesor | Nosotros | Por qué |
|---|----------|----------|---------|
| 1 | Dos Postgres (FastAPI `pgvector` en 5433 + Rails) | **Un solo** Postgres `pgvector` en 5432 | Veníamos de Sesión 5/6 con un único Postgres compartido |
| 2 | Driver `psycopg` (v3) | Driver `psycopg` (v3) — ✅ **alineado en S8** | Migrado desde `psycopg2-binary` (Sesiones 5–6) a `psycopg[binary]` para ir igual que el oficial; el swap async queda idéntico al suyo |
| 3 | `SessionStore` en memoria (conversaciones) | **`DbSessionStore`** (Postgres) | Desvío de la Sesión 5: la memoria conversacional sobrevive a reinicios. **No se toca en S8** |
| 4 | `records` / telemetría no existen | `app/api/records.py`, `db_models.py` | Funcionalidad propia (CRUD+ciclo de vida+coste). Intacta |
| 5 | `greenlet` vía `uv.lock` | `greenlet>=3.0` explícito en `pyproject.toml` | Lo necesita el motor async de SQLAlchemy |
| 6 | — | **Fix:** `env.py` importaba `app.persistence.models` (obsoleto) → `app.foundation.persistence.models` | Bug latente de la reorganización de S7 |
| 7 | — | **Fix:** `db.py::create_all` importaba `from app import db_models` (obsoleto) → `app.foundation.persistence` | Mismo origen; rompía la creación de tablas de conversación al arrancar |

Los puntos 6 y 7 son **bugs preexistentes** de la reorganización por capas de la Sesión 7 que sólo
se manifiestan al ejecutar la app/migraciones de verdad (los tests no los disparaban). Persistir en
BD los hizo aflorar y se corrigieron.

---

## 14. Verificación

```bash
# 1) Migración (cadena 0001 → 0002), extensión y tablas
uv run alembic upgrade head
#    documents | chunks | ingestion_jobs | pseudonym_mappings ; pg_extension → vector

# 2) Suite completa + lint
uv run pytest -q          # 245 passed (227 previos + 18 nuevos de Sesión 8)
uv run ruff check .       # All checks passed!

# 3) Búsqueda real de extremo a extremo
docker compose up -d
docker compose run --rm estimator python scripts/query_examples.py
```

Comprobaciones reales hechas en esta entrega:

- **245 tests** en verde (18 nuevos: `test_rag_store_models.py`, `test_embeddings_ingest_persist.py`,
  `test_search_endpoint.py`). Los tests nuevos son *infra-free*: usan fakes/introspección, no
  necesitan Postgres ni OpenAI.
- **Migración aplicada** sobre un Postgres real: `documents`, `chunks`, extensión `vector` activa.
- **15 documentos / 60 chunks**, los 60 con vector (chunk+embedding atómico).
- **`/search`** devuelve el contrato completo ordenado por distancia coseno ascendente.
- **409** devuelve la forma literal `{"detail": "Document already ingested", "document_id": 1}`.

---

## 15. Entregable (checklist)

| Entregable | Estado | Dónde |
|------------|--------|-------|
| `docker-compose.yml` con servicio `postgres` (pgvector) | ✅ (ya existía) | `estimator/docker-compose.yml` |
| Migración Alembic (extensión + 2 tablas + índices no-vectoriales) | ✅ | `alembic/versions/0002_session8_pgvector.py` |
| `POST /embeddings/ingest` refactorizado para persistir + 409 | ✅ | `app/api/embeddings.py`, `app/generation/rag/ingest_service.py` |
| `POST /search` nuevo y funcional | ✅ | `app/api/search.py`, `app/generation/rag/retriever.py` |
| Script `query_examples.py` ejecutable | ✅ | `scripts/query_examples.py` |
| `output_examples.txt` con el output real | ✅ | `estimator/output_examples.txt` |
| Sección nueva en el README (≤1 página, 4 justificaciones) | ✅ | `README.md` § *pgvector persistence + semantic search* |

---

> **Referencias cruzadas:** el recorrido del código pieza a pieza está en
> [`codigo-explicado.md`](../codigo-explicado.md) §22. La línea base de la Sesión 7 (chunking,
> embeddings, arquitectura por capas) está en [`session-07.md`](../session-07.md). La **teoría**
> subyacente a esta sesión está resumida en [`session-08-theory.md`](session-08-theory-rag-bbdd-vectoriales.md).
