# Sesión 7 — RAG: chunking, embeddings y arquitectura por capas

> Este documento cubre **dos momentos** de la Sesión 7:
>
> - **Parte 1 — el ejercicio previo al directo:** un pipeline mínimo (`embedding_pipeline/`) que
>   parte presupuestos en *chunks*, los convierte en vectores con OpenAI y los devuelve por HTTP.
> - **Parte 2 — la sesión en vivo:** la gran reorganización del servicio en **capas**
>   (`foundation` / `domain` / `generation` / `ingestion` / `api`), el **laboratorio de chunking**
>   (siete estrategias comparables) y el **cambio de modelo en caliente** desde la API.
>
> No se toca la interfaz Angular ni el backend de negocio. La persistencia en base de datos
> vectorial (pgvector) sigue siendo deliberadamente de la **Sesión 8**. Las **divergencias** de
> esta implementación respecto al repo oficial del profesor se señalan a lo largo del texto y se
> resumen en [`ARCHITECTURE.md`](../ARCHITECTURE.md) §10.

---

## 0. Explicación para cualquiera (sin tecnicismos)

Imagina una caja de **presupuestos antiguos** de proyectos de software. Cada presupuesto tiene un
resumen y una lista de *componentes* ("backend de login", "pasarela de pagos", "panel de
administración"…), cada uno con su descripción, su tecnología y sus horas.

Queremos poder **buscar por significado**: "enséñame presupuestos parecidos a *autenticación con
OAuth para banca*", aunque las palabras exactas no coincidan. Para eso, el ordenador convierte
cada texto en una lista de números que captura *de qué trata* — eso es un **embedding**. Dos
textos que hablan de lo mismo tienen listas de números parecidas; dos sin relación, listas
distintas.

Pero no se puede meter un presupuesto entero de golpe: hay que **trocearlo** en pedazos con
sentido. A trocear se le llama *chunking*. Y aquí está la novedad del directo: **no hay una única
forma correcta de trocear**. Puedes cortar por componentes, por tamaño fijo, por frases, por
"cambios de tema", pedirle a otra IA que resuma el contexto de cada trozo… Cada forma tiene un
**equilibrio distinto** entre precisión, exhaustividad y coste. La sesión en vivo monta un
**laboratorio** que prueba siete formas sobre los mismos presupuestos y las compara.

Además pasaron dos cosas más:

1. **Ordenamos la casa.** El código había crecido en muchas carpetas sueltas. Lo reorganizamos en
   **habitaciones con una función clara** (capas): los cimientos, el contrato, las "tres IAs" que
   componen el producto, la ingesta de datos y la fachada web. Una regla de oro: las tres IAs **no
   se hablan entre sí directamente**, sólo a través de un único "director de orquesta".
2. **Pusimos un mando para cambiar el "cerebro" en caliente.** Ahora se puede cambiar el modelo de
   lenguaje (de GPT a Claude, por ejemplo) **sin reiniciar nada**, desde una llamada a la API.

El resto del documento explica cada pieza, primero para humanos y luego con el detalle técnico.

---

# PARTE 1 — El pipeline mínimo (ejercicio previo al directo)

## 1.1 Objetivo

Construir dentro del servicio IA un pipeline funcional mínimo que reciba presupuestos históricos en
JSON, los parta en *chunks* respetando la estructura del documento, genere embeddings con OpenAI
(`text-embedding-3-small`) y devuelva los vectores listos para uso posterior. Se cierra con un
script CLI que verifica que los embeddings discriminan bien comparando la similitud coseno entre
tres parejas de textos. El producto **no se persiste todavía**: los vectores se generan en memoria
y se devuelven por HTTP.

## 1.2 Chunking estructural: un componente = un chunk

`JSONStructuralChunker.chunk(budgets)` itera presupuestos y, por cada `BudgetComponent`, produce un
`Chunk`. **No** hay *overlap* ni *fixed-size splitting* de descripciones largas: se confía en la
estructura del JSON. En el dataset de ejemplo cada chunk mide **67–104 tokens**. Si una descripción
fuese excepcionalmente larga, eso es un dato a discutir, no algo que partir a ciegas.

**Cabecera de contexto (*contextual chunk header*).** El `text` que se embebe no es sólo la
descripción del componente: lleva delante el contexto del presupuesto padre.

```
[Project: {project_summary}]
[Client sector: {sector} | Year: {year} | Main tech: {main_technology}]

Component: {name}
Description: {description}
Tech stack: {tech_stack join ", "}
Complexity: {complexity}
Estimated hours: {estimated_hours}
```

Sin esa cabecera, un componente "Authentication backend" perdería la pista de a qué cliente y
sector pertenece, y los embeddings de descripciones sueltas colapsarían entre proyectos muy
distintos.

## 1.3 `token_count` con el mismo tokenizador que embebe

Se cuenta con la codificación `cl100k_base` (la de `text-embedding-3-small`). Contar con el *mismo*
tokenizador que luego embebe permite detectar chunks anormalmente grandes **antes** de pagar la
llamada a la API.

## 1.4 Embedder: lotes, reintentos y coste

- **Lotes:** `embed_many` llama a `embeddings.create` con **listas** de hasta 100 chunks por
  petición (el endpoint acepta listas), no una llamada por chunk.
- **Reintentos:** `RateLimitError` se reintenta con *backoff* exponencial (1s, 2s, 4s); cualquier
  otro error se propaga.
- **Orden preservado:** la respuesta se ordena por `index` por si la API la devuelve desordenada
  (este es un detalle **divergente** respecto al embedder oficial, que asume el orden de entrada).
- **Coste:** `estimated_cost_usd = total_tokens / 1e6 * 0.02` ($0.02 por millón de tokens de
  entrada), con la constante claramente etiquetada porque cambia con el tiempo.
- **Dimensión por defecto (1536):** no se fuerza una dimensión menor; la discusión sobre
  *Matryoshka* (truncar el vector para ahorrar memoria) se trató en el directo.

## 1.5 El endpoint `POST /embeddings/ingest`

El handler es un orquestador fino: `chunker.chunk(budgets) → embedder.embed_many(chunks) →
IngestResponse`. Devuelve los vectores y unas estadísticas (nº de presupuestos, chunks, tokens y
coste estimado). El prefijo es `/embeddings` (no `/api/v1`) para respetar el enunciado al pie de la
letra y que la ruta aparezca exactamente así en `/docs`.

## 1.6 `compare.py` — el test de humo de similitud coseno

CLI (`scripts/embedding/compare.py`, `--text-a`/`--text-b`) que reutiliza `OpenAIEmbedder` y calcula
el coseno **a mano** (producto escalar / producto de normas, sin numpy ni scikit-learn). La idea: si
dos frases que significan lo mismo dan un número alto y dos sin relación dan uno bajo, los embeddings
funcionan.

**Resultados reales** (detalle en [`scripts/embedding/SANITY_CHECK.md`](../scripts/embedding/SANITY_CHECK.md)):

| Pareja | Esperado | Coseno |
|--------|----------|--------|
| A — cercanas (OAuth/JWT fintech ↔ "JSON Web Tokens for a banking application") | alto (≳ 0.6) | **0.5957** |
| B — no relacionadas (OAuth ↔ "MySQL→PostgreSQL migration") | bajo (≲ 0.4) | **0.1920** |
| C — genéricas ("Backend services" ↔ "API development") | sin expectativa | **0.5407** |

Orden **A > C > B**. Se cumple el mínimo (**A ≫ B**: el embedding discrimina). Dos hallazgos para el
directo: (1) A se queda *rozando por debajo* del 0.6 —el modelo capta los sinónimos pero la
reformulación completa no llega al umbral; el 0.6 es guía, no frontera dura—; y (2) **C ≈ A**: dos
etiquetas genéricas y cortas dan casi la misma similitud que una pareja sinónima, porque los textos
cortos sin contexto colapsan hacia el mismo macro-dominio. Es justo el argumento del *contextual
chunk header*.

## 1.7 Datos de ejemplo (`data/budgets_sample.json`)

El fichero **no se entregó** en el repo de datos del programa, así que se creó uno propio: **15
presupuestos** normalizados que cubren cuatro sectores (`fintech`, `e-commerce`, `healthcare`,
`industrial`) y stacks variados, con 4 componentes cada uno → **60 chunks**. La variedad es
deliberada: da señal con la que discriminar en el *sanity check* y, en la Sesión 8, en el retrieval.

> **Divergencia importante para la Parte 2:** como nuestros sectores son cadenas libres (`fintech`,
> `e-commerce`…), conservamos un `schemas.py` con `sector: str` abierto y `extra="ignore"`. El
> esquema del profesor cierra el sector a un `Literal` de cuatro valores. Mantener el nuestro evita
> que nuestro `budgets_sample.json` falle la validación (ver §2.2).

---

# PARTE 2 — La sesión en vivo

## 2.1 La gran reorganización: arquitectura por capas

### Para humanos

Hasta ahora el código vivía en una lista plana de carpetas (`services/`, `cache/`, `routers/`,
`sessions/`, `guardrails/`, `prompts/`…). Funcionaba, pero cada sesión añadía carpetas nuevas y
empezaba a costar saber **dónde vive cada cosa** y **qué puede hablar con qué**. El riesgo: que el
proyecto degenere en una maraña de carpetas acopladas donde tocar una cosa rompe otra.

La sesión en vivo lo reorganiza como una **cocina de restaurante con estaciones**: cada estación
tiene una función y un orden claro. La idea central es que el estimador no es **una** técnica de IA,
sino **tres apiladas**, y conviene que el código lo refleje:

- **CAG — *Cache-Augmented Generation*** (`generation/cag/`): responde **sin tocar el LLM** cuando ya
  hay una respuesta equivalente (acierto exacto por hash, luego por similitud vectorial).
- **RAG — *Retrieval-Augmented Generation*** (`generation/rag/`): convierte el corpus de presupuestos
  en chunks + embeddings y —desde la Sesión 8— los recuperará para enriquecer el prompt con
  conocimiento citable. **Aquí vive el laboratorio de chunking de esta sesión.**
- **Agéntica** (`generation/agentic/`): el bucle Actor-Crítico-Boss que itera y audita la estimación
  antes de aceptarla, apoyado en la conversación multi-turno (`generation/conversation/`).

**La regla de oro:** estas tres capas **no se conocen entre sí**. Componen únicamente a través de un
"director de orquesta", el **conductor** (`domain/estimation_service.py`). Si dos capas necesitan
colaborar, el método que las une va en el conductor, **nunca** con un import cruzado. Eso es lo que
impide que el proyecto vuelva a enmarañarse.

### Para técnicos: el pastel de cinco capas

```
app/
├── config.py · dependencies.py · main.py   # raíz: composition root, por encima de las capas
├── foundation/   llm · prompts · guardrails · attachments · persistence   # plomería, sin opinión de IA
├── domain/       schemas/ (el contrato) + estimation_service.py (el conductor)
├── generation/   cag/ · rag/ · agentic/ · conversation/   # las 3 arquitecturas + substrato
├── ingestion/    pipeline batch (offline) que alimenta RAG
└── api/          routers finos (transporte), sin lógica de negocio
```

Cada capa **sólo puede importar de las que tiene por encima**: `foundation` sólo importa `config`;
`generation/<x>` importa `foundation` + `domain/schemas` pero **nunca a otro hermano de
`generation`** (la única excepción documentada: `agentic` puede importar `conversation`). El
contrato completo, con la tabla de dependencias permitidas y el mapa de migración vieja→nueva, está
en [`ARCHITECTURE.md`](../ARCHITECTURE.md).

**Lo que esta reorganización significa para la Parte 1:** el módulo `embedding_pipeline/` se
descompone y se reparte dentro de `generation/rag/`:

| Antes (pre-directo) | Ahora (por capas) |
|---|---|
| `embedding_pipeline/chunker.py` | `generation/rag/chunking/structural.py` |
| `embedding_pipeline/embedder.py` | `generation/rag/embedding/embedder.py` |
| `embedding_pipeline/schemas.py` | `generation/rag/schemas.py` |
| `embedding_pipeline/router.py` | `api/embeddings.py` |
| *(no existía)* | `generation/rag/chunking/{base.py, strategies/}` ← **nuevo, el laboratorio** |
| *(no existía)* | `generation/rag/analysis/{similarity.py, comparison.py}` ← **nuevo** |
| *(reservado)* | `generation/rag/{store/, retriever.py}` ← **vacío, Sesión 8** |

### Qué conservamos (divergencias)

La reorganización respeta nuestros cuatro desvíos respecto al oficial, y todos **encajan dentro del
contrato de capas**:

1. **API de estimaciones persistidas** (`api/records.py` + `domain/schemas/record.py`): un CRUD
   `/api/v1/estimations/*` que guarda cada estimación y la ejecuta (`/run`). El oficial no persiste
   estimaciones.
2. **Doble base de datos** en `foundation/persistence/`: `db.py`/`db_models.py` (S5:
   `estimations`, `chat_sessions`) conviven con `database.py`/`models.py`/`repositories/` (S6:
   Alembic). Mismo Postgres, dos `Base`.
3. **Memoria conversacional en Postgres** (`DbSessionStore`), no el `SessionStore` en memoria del
   oficial. Por eso `conversation/store.py` importa el ORM de `foundation/persistence/` (import
   legal: `generation` puede importar `foundation`).
4. **Cliente Angular** (`estimator-frontend/`) en lugar del Rails `estimator-web/` del oficial.

## 2.2 El laboratorio de chunking: siete formas de trocear

### Para humanos

Cómo trocees el corpus condiciona **lo bien que luego encuentras** lo que buscas. Trozos demasiado
grandes diluyen el significado (el vector "mezcla" varios temas); demasiado pequeños pierden
contexto. Y algunas técnicas pagan un coste extra (llamadas a un LLM o a la API de embeddings) **en
el momento de ingerir**, antes de servir una sola consulta. No hay una ganadora universal: hay un
**equilibrio** entre precisión, exhaustividad y coste. Por eso se monta un laboratorio que ejecuta
varias estrategias sobre los **mismos** presupuestos y las pone una al lado de otra.

### Las siete estrategias (interfaz común `Chunker`)

Todas implementan la misma interfaz (`base.py`: `chunk(budgets) -> list[Chunk]` + `strategy_name`),
así que son intercambiables. Todas cuentan tokens con el mismo tokenizador y emiten el mismo evento
de log (`chunking_done`) para que las cifras sean comparables.

| Estrategia | Idea (humano) | Detalle técnico | ¿Coste extra al ingerir? |
|---|---|---|---|
| **structural** | Un componente del presupuesto = un trozo. La línea base sensata. | Itera componentes; cabecera de contexto del padre. | No |
| **fixed_size** | Cortar a ciegas cada 512 tokens. El "suelo" contra el que medir. | Ventana deslizante con *overlap* de 80; ignora toda frontera natural. | No |
| **recursive** | Cortar por separadores naturales (párrafo→línea→frase→palabra). El **defecto razonable**. | `RecursiveCharacterTextSplitter.from_tiktoken_encoder`. | No |
| **sentence_window** | Indexar frases sueltas (precisión) pero llevar una ventana de ±2 frases para dar al LLM contexto. | Tokeniza con NLTK; la frase se embebe, la ventana viaja en `metadata`. | No (descarga NLTK *punkt* la 1ª vez) |
| **semantic** | Cortar donde **cambia el tema**, no por tamaño. | Embebe frases consecutivas y corta en el percentil 95 de "distancia"; **embebe todo el corpus al ingerir**. | **Sí** (≈1 pasada de embeddings) |
| **propositional** | Pedir a un LLM que parta cada componente en **hechos atómicos** autocontenidos. | Una llamada a `gpt-4o-mini` por componente (Instructor → `list[str]`); fallback a 1 chunk si falla. | **Sí** (1 llamada LLM/componente) |
| **contextual_retrieval** | Técnica de Anthropic: un LLM escribe un **párrafo que sitúa** cada trozo en su presupuesto y se le pega delante. | Claude con `cache_control` sobre el documento padre (se paga el prefijo una vez por presupuesto). | **Sí** (la más cara; *prompt caching* la abarata) |
| **hierarchical** | Indexar a dos niveles: hijos (componentes, precisos) y padre (presupuesto entero, contexto). | Cada hijo lleva `parent_chunk_id`; el retriever de S8 decidirá qué nivel devolver. | No |

### El marco de comparación (`analysis/comparison.py`)

Dos señales informales (las métricas formales —*recall@k*, NDCG— son de la Sesión 11):

1. **Estadísticas de corpus** por estrategia: nº de chunks, distribución de tokens (min/p50/p95/max),
   y cuántos chunks son **huérfanos** (< 20 tokens) u **obesos** (> 800 tokens). De un vistazo se ve
   qué estrategia descompone con sensatez y cuál se rompe. Incluye coste de ingesta y segundos.
2. **Top-k coseno** sobre un set fijo de consultas: para cada consulta, los mejores chunks que
   recupera cada estrategia, con su similitud, listos para juzgar a ojo.

Cada estrategia se chunkea **una sola vez** por corpus y se memoiza, para que pedir estadísticas y
consultas no duplique las (caras) llamadas LLM de `propositional` o `contextual_retrieval`.

### El endpoint `POST /embeddings/compare`

Recibe `budgets`, `queries` opcionales, una lista de `strategies` (vacía = todas) y `top_k`. Devuelve
`stats_per_strategy` y `queries_per_strategy`. Nada se persiste (eso es Sesión 8). Las estrategias con
coste se construyen **por petición** (no se cachean) para que un cambio de modelo en caliente (§2.3)
surta efecto en la siguiente comparación. Si falta la API key de una estrategia, el endpoint devuelve
un 500 con el motivo.

### Resultado real (offline, sobre nuestro `budgets_sample.json`)

Las estrategias sin coste corren sin red ni API key. Sobre nuestros 15 presupuestos:

| Estrategia | nº chunks | tokens p50 / p95 / max |
|---|---|---|
| structural | 60 | 78 / 90 / 104 |
| fixed_size | 60 | 78 / 90 / 104 |
| recursive | 15 | 220 / 251 / 274 |
| hierarchical | 75 | 82 / 231 / 274 |

Se lee mucho de un vistazo: con nuestros componentes pequeños, `fixed_size` coincide con `structural`
(cada componente cabe en una ventana de 512 tokens, no llega a cortar); `recursive` produce **1 chunk
por presupuesto** (el presupuesto entero serializado cabe bajo 512 tokens), trozos más grandes y
menos numerosos; `hierarchical` añade los 15 padres a los 60 hijos. Las tres estrategias con coste
(`semantic`, `propositional`, `contextual_retrieval`) requieren clave de OpenAI/Anthropic y se dejan
para ejecutarse en el directo, midiendo su coste con el campo `ingestion_cost_usd`.

## 2.3 Cambio de modelo en caliente (runtime model config)

### Para humanos

Antes, cambiar el modelo de lenguaje significaba editar `.env` y **reiniciar** el contenedor. Ahora
hay un **mando en el panel**: una llamada a la API cambia el modelo (de `gpt-4o-mini` a
`claude-sonnet-4-5`, por ejemplo) y surte efecto en la **siguiente** llamada, sin reiniciar nada y
sobreviviendo a los reinicios.

### Para técnicos

- **`foundation/llm/runtime_config.py`**: un almacén de *overrides* respaldado por un *hash* de Redis.
  `.env` sigue siendo la capa de **valores por defecto**; Redis guarda sólo las **diferencias**.
  `effective(key)` devuelve el override si existe, si no el default. Lecturas que degradan con
  elegancia (si Redis cae, se usa el default); escrituras que re-lanzan (un override fallido debe ser
  visible → 503).
- **`api/config.py`**: `GET/PUT /api/v1/config/models`. El `GET` devuelve, por cada knob,
  `{effective, default, overridden}` + el catálogo de modelos disponibles (filtrado por las API keys
  realmente configuradas). El `PUT` valida **todo antes de escribir nada** (todo-o-nada).
- **Cómo fluye el override** sin reconstruir objetos: el `LLMWrapper` expone `primary_model` /
  `fallback_model` como **propiedades** que leen Redis en cada llamada (el `Router` de LiteLLM
  conserva los *deployments* iniciales por seguridad de hilos; cuando el modelo efectivo difiere del
  inicial, la llamada va directa, sin fallback). Los chunkers `propositional`/`contextual` leen su
  modelo del store en su *factory*. **En este repo**, además, el `EstimationService` resuelve
  `CRITIC` / `METADATA` / `COMPRESSION` como propiedades (divergencia: el conductor lleva su propio
  `runtime_config`), de modo que los siete knobs del store surten efecto de verdad.
- **`EMBEDDING_MODEL` queda fuera** a propósito: cambiarlo invalidaría todos los vectores ya
  almacenados, así que se mantiene sólo en `.env`.

## 2.4 Dependencias nuevas (`pyproject.toml`)

El laboratorio de chunking añade cuatro librerías (instaladas en el venv; `anthropic` y `tiktoken` ya
estaban):

- `langchain-text-splitters` — `RecursiveCharacterTextSplitter` (estrategia recursive).
- `langchain-experimental` + `langchain-openai` — `SemanticChunker` + `OpenAIEmbeddings` (semantic).
- `nltk` — tokenización en frases (sentence_window; descarga *punkt* la primera vez).

## 2.5 Verificación

```bash
cd estimator

# 1) La app arranca y registra las rutas nuevas (compare + config) sin perder las nuestras (records)
uv run python -c "from app.main import app; r=sorted({x.path for x in app.routes}); \
  assert '/embeddings/compare' in r and '/api/v1/config/models' in r and '/api/v1/estimations' in r; print('routes OK')"

# 2) Laboratorio de chunking offline (sin API) sobre el sample
uv run python -c "import json; from app.generation.rag.schemas import Budget; \
  from app.generation.rag.chunking.strategies import RecursiveChunker; \
  b=[Budget(**x) for x in json.load(open('data/budgets_sample.json'))]; \
  print('recursive ->', len(RecursiveChunker().chunk(b)), 'chunks')"

# 3) Suite completa + lint
uv run pytest -q          # 227 passed
uv run ruff check .       # All checks passed!
```

Resultado obtenido: **227 tests verdes** (sin regresiones respecto a la base), **ruff limpio**, la
app arranca con las rutas nuevas y el laboratorio de chunking corre offline sobre nuestros datos
(structural 60, fixed_size 60, recursive 15, hierarchical 75 chunks). Las estrategias con coste y el
`/embeddings/compare` con consultas reales requieren API keys con saldo y se ejecutan en el directo.

## 2.6 Entregable (actualizado tras el directo)

- ✅ **Reorganización por capas** completa (`foundation`/`domain`/`generation`/`ingestion`/`api`),
  con todos los imports reescritos y `ARCHITECTURE.md` como contrato.
- ✅ **Laboratorio de chunking**: `generation/rag/chunking/{base.py, structural.py, strategies/*}`
  (7 estrategias) + `generation/rag/analysis/{similarity.py, comparison.py}`.
- ✅ **Endpoint `POST /embeddings/compare`** registrado, junto al `/embeddings/ingest` previo.
- ✅ **Cambio de modelo en caliente**: `foundation/llm/runtime_config.py` + `GET/PUT
  /api/v1/config/models`, cableado en wrapper, chunkers y conductor.
- ✅ **Slots reservados para la Sesión 8**: `generation/rag/store/` + `generation/rag/retriever.py`.
- ✅ Divergencias preservadas (records, doble BD, `DbSessionStore`, Angular) y documentadas.
- ✅ `pyproject.toml` + `.env.example` actualizados; **227 tests** verdes; ruff limpio.
- ✅ Parte 1 intacta: `compare.py`, `SANITY_CHECK.md` (0.5957 / 0.1920 / 0.5407) y
  `budgets_sample.json`.
