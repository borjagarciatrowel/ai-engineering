# Sesión 08 — Bases de datos vectoriales, índices y pgvector (versión clara)

> Versión simplificada del resumen de los 5 artículos de la Sesión 8.
> Misma información, menos paja. Cada término técnico se explica en una frase.
> **Hilo conductor:** guardar bien los embeddings de presupuestos y poder buscar por significado a escala — y decidir *cuándo*, *cuál* y *cómo* llevarlo a producción.

---

## Glosario base (léelo una vez y vuelve cuando haga falta)

| Término | Qué es, en una frase |
|---|---|
| **Embedding** | Una lista de números (un "vector") que captura el significado de un texto. Textos parecidos → vectores cercanos. |
| **Vector / dimensión** | El embedding es un punto en un espacio de muchas dimensiones (los de OpenAI: **1536**). "Cercanía" ahí ≈ parecido de significado. |
| **Chunk** | Un trozo de documento (un párrafo, una sección). Indexamos chunks, no documentos enteros. |
| **KNN exacto** | Comparar tu consulta contra **todos** los vectores. Siempre acierta, pero el coste crece con el nº de vectores. |
| **ANN aproximado** | Usar estructuras listas (grafos, particiones) que miran **solo unos pocos** vectores prometedores. Acepta fallar de vez en cuando a cambio de ser mucho más rápido. |
| **Recall** | De todo lo relevante que existe, cuánto trajiste. Con ANN, ~95–99 %. |
| **Índice vectorial** | El "truco" (IVFFlat, HNSW, DiskANN) que evita comparar contra todos los vectores. |
| **pgvector** | La extensión que convierte PostgreSQL en base de datos vectorial, sin añadir un sistema nuevo. |
| **ACID** | Garantías transaccionales: una operación se completa entera o se revierte entera (no a medias). |
| **Latencia** | Cuánto tarda en responder. El coste que más duele. |

---

## La idea en una página

En la Sesión 7 el programa convertía presupuestos en embeddings y comparaba por parecido, pero esos números **vivían en memoria y se perdían al apagar el servicio.** La Sesión 8 trata de **guardarlos bien y buscar por significado a escala.** Para eso existen las **bases de datos vectoriales.**

Analogía: una biblioteca gigante donde cada párrafo tiene una **coordenada** según de qué trata. Guardar = colocar cada párrafo en su coordenada. Buscar = ir a la coordenada de tu pregunta y coger los párrafos más cercanos. El problema: "buscar lo más cercano" en **1536 dimensiones** (no 2 ni 3) es un problema de cómputo distinto al de una base de datos normal. Dos formas de resolverlo:

- **KNN exacto:** comparas contra **todos** los vectores. Aciertas siempre; coste lineal. Con cientos, invisible; con millones, inviable.
- **ANN aproximado:** estructuras inteligentes miran **solo unos pocos** vectores. Aceptas equivocarte muy de vez en cuando (recall ~98–99 %) a cambio de ser **cientos o miles de veces más rápido.**

> Una base de datos vectorial es, en esencia, **índices ANN sobre almacenamiento persistente**, accesibles por SQL o API.

La gran pregunta de la sesión no es solo *cómo* funciona, sino *cuándo* la necesitas (no siempre), *cuál* eliges (depende) y *cómo* la llevas a producción sin sorpresas. El programa elige **pgvector**: PostgreSQL haciendo más cosas, sin añadir un sistema nuevo al stack.

---

# PARTE 1 — Por qué existen y cuándo las necesitas

## 1.1 El hueco que deja el prototipo

Los vectores en memoria (`list` de Python + `numpy`) son una mini base de datos vectorial: calculas cosenos y ordenas. Funciona, e incluso es rápido a escala pequeña (numpy es C por debajo). **Cuatro propiedades que un array no te da:**

1. **Persistencia.** Un proceso que muere se lleva todos los vectores. Re-embeber el corpus en cada reinicio cuesta tiempo y **dinero** (cada llamada a la API de embeddings se paga).
2. **Concurrencia.** Con dos réplicas detrás de un balanceador, cada una tiene su estado en memoria y divergen: una ingesta va a la réplica A, una búsqueda a la B y no encuentra lo recién ingestado. Solución: **delegar la persistencia a un sistema diseñado para ello.**
3. **Consultas combinadas con datos relacionales.** Casi nunca quieres "los 5 chunks más parecidos" sin más, sino "los 5 más parecidos **del sector fintech, de los últimos 2 años, con monto <100k**". Una BBDD vectorial sobre motor relacional **mezcla búsqueda semántica y filtros en una sola query atómica.**
4. **Operaciones transaccionales (ACID).** Ingestar = 1 fila en `documents` + N filas en `chunks`. Si el embedder falla en el chunk 5, quieres **revertir**, no quedarte con un documento huérfano.

## 1.2 El problema técnico que ningún sistema anterior resuelve

> **Índice B-tree** = el índice clásico de las bases de datos relacionales; aprovecha que los valores son **ordenables linealmente** (números, fechas, texto).

PostgreSQL está optimizado para "¿existe el registro `id = 42`?" con índices B-tree. Pero "¿qué presupuestos son **semánticamente parecidos** a este brief?" no se responde comparando valores exactos: se responde comparando vectores de 1536 dimensiones y devolviendo los *k* más cercanos. **No hay forma de indexar "cercanía en 1536 dimensiones" con un B-tree.** Es una **primitiva nueva**, no una optimización marginal.

### KNN exacto vs ANN aproximado (el cambio mental clave)

Hasta ahora todo sistema devolvía respuestas **deterministas**: pides `id = 42`, recibes `id = 42`, siempre. Las BBDD vectoriales con índices ANN **no funcionan así**:

| | **KNN exacto** (sequential scan) | **ANN aproximado** (HNSW, IVFFlat…) |
|---|---|---|
| Cómo funciona | Distancia contra **cada** vector, ordena | Navega grafo / particiones, mira **solo** vecinos probables |
| Latencia | **O(n)** lineal | **O(log n)** o casi constante |
| Recall | **100 %** garantizado | **~95–99 %** (ajustable) |
| Determinismo | Sí | **No** (reindexar con otros parámetros cambia resultados) |
| Viable hasta | ~10K vectores | decenas de millones |

El trade-off de ANN: **perder ~1–2 % de recall a cambio de latencia 100×–1000× menor.** Para un RAG que devuelve 5 chunks, ese 1–2 % es invisible; la diferencia entre 5 ms y 5000 ms no lo es.

Dos implicaciones:
- **El recall se mide, no se asume.** Antes de poner un índice ANN en producción, comparas sus resultados contra la verdad de fondo (búsqueda exacta sin índice) sobre queries representativas. Mecánica nueva que no existía en el mundo relacional.
- **El debugging cambia.** Si una búsqueda devuelve algo raro, antes de culpar al modelo o al chunking, verifica que **el índice no esté siendo ignorado en silencio** (ver antipatrón, Parte 4).

## 1.3 Cuándo añadirla — y cuándo no

Decisión por criterio operativo, no por reflejo. Tres umbrales de escala:

- **< 10K vectores (sobre todo si son estáticos):** un `numpy` cargado al arrancar es razonable. KNN exacto tarda milisegundos. Añadir una BBDD vectorial aquí es **over-engineering** (el error que casi todos los tutoriales empujan desde el día uno).
- **10K – 50M vectores:** la BBDD vectorial es la respuesta correcta. El **sweet spot** donde caen casi todos los productos B2B con IA — incluido el sistema de estimaciones. La pregunta ya no es "¿necesito una?" sino "¿cuál?".
- **> 50–100M vectores:** sistemas distribuidos (Milvus, Vespa), sharding, índices que no caben en RAM (DiskANN). Fuera del foco del programa.

> **Un cuarto caso:** si tu problema **no requiere similitud semántica** (matches exactos de nombres, IDs, SKUs), una búsqueda full-text con `tsvector` o un índice trigram resuelve mejor y con menos complejidad. La búsqueda semántica vale **cuando los términos exactos varían pero el significado no.** Si consultas y datos comparten vocabulario, la BBDD vectorial es un martillo sobre algo que no es un clavo.

El proyecto de estimaciones cae claramente en el rango medio, y los datos sí varían en vocabulario (un brief raramente usa las mismas palabras que los presupuestos históricos). La búsqueda semántica es la primitiva correcta.

---

# PARTE 2 — El mapa del mercado 2026

## 2.1 Los cuatro ejes que importan

Una comparativa basada solo en QPS o solo en precio te deja a medias. Cuatro ejes:

> **QPS** = *queries per second*, consultas por segundo que aguanta el sistema.
> **Self-hosted vs managed** = lo gestionas tú (control total, pero updates/backups/monitorización/guardias) o el proveedor (pagas por no pensar, menos control, coste que escala con el uso).

1. **Modelo operativo.** ¿Self-hosted o managed?
2. **Escala práctica.** No "cuántos vectores caben" sino "cuántos soporta con **latencias aceptables, recall razonable y coste que no se dispara**". Benchmarks 2026: <10M cualquiera vale; 10–100M el campo se estrecha; >1B solo sistemas diseñados para esa escala.
3. **Funcionalidades nativas.** ¿Búsqueda híbrida (vector + keyword) de serie o la compones tú? ¿Filtrado por metadata *first-class* o *add-on*? ¿Multimodal? ¿Sharding multi-región?
4. **Modelo de coste.** La factura mensual es solo **una** de tres componentes. Las otras: **coste de operación** (DevOps, on-call) y **coste de migración** el día que cambies (re-indexar decenas de millones no es un fin de semana).

## 2.2 Las cinco opciones

- **pgvector — la extensión de Postgres.** No es una BBDD nueva: es Postgres haciendo más cosas. Añade el tipo `vector`, operadores de distancia e índices ANN (HNSW desde 0.5, IVFFlat antes). Si tu equipo ya opera Postgres, es un `CREATE EXTENSION vector`. La narrativa de "Postgres es lento para vectores" viene de la era de IVFFlat y ya no se sostiene: con HNSW bien dimensionado compite con los dedicados hasta ~10M vectores, y con `pgvectorscale` (DiskANN + cuantización) el techo sube mucho. **Ventaja única:** cruzar búsqueda vectorial con datos relacionales en **una sola query SQL atómica con ACID.** Techo: cuando el volumen excede `shared_buffers` (I/O de disco por query) o necesitas funciones muy específicas.
- **Qdrant — el líder de velocidad open-source.** Dedicada, escrita en Rust. Rendimiento puro y **filtrado por metadata best-in-class** (p50 < 5 ms a alto recall). Brilla en cargas *read-heavy* con filtros complejos. Se queda corto en operaciones no vectoriales (no hay joins ni garantías transaccionales sobre datos relacionales). Sweet spot: cientos de miles a decenas de millones.
- **Weaviate — búsqueda híbrida nativa.** Su seña: combinar similitud vectorial con BM25 sobre keywords de forma nativa. Trae módulos de vectorización integrados. Precio: modelo más opinado (esquema de clases, API GraphQL, *coupling*). Ideal cuando la híbrida es el centro del producto (documentos legales, e-commerce con SKUs, compliance).
- **Milvus — la escala de mil millones.** Diseñada para escala extrema: arquitectura distribuida, sharding maduro, soporte GPU, *backing* por Zilliz. La open-source más popular por estrellas. Por debajo de 100M está **sobredimensionada** (etcd, MinIO, varios servicios). Por encima de 1B, una de las pocas que funciona de verdad.
- **Pinecone — la opción gestionada.** Totalmente gestionada, propietaria, vende *zero ops*. Para equipos pequeños donde el coste de un DevOps dedicado supera la factura. Coste en tres componentes (storage $0.33/GB/mes, *read units*, *write units*) + mínimo $50/mes. **Aviso:** benchmarks recientes reportan que la factura real promedia **2.5×–4×** la estimación del calculador. Por encima de ~10M con tráfico sostenido, self-hosted suele ser 3×–10× más barato en TCO. En industrias reguladas con soberanía de datos, queda fuera.

| Opción | Modelo operativo | Escala práctica | Funcionalidad distintiva | Cuándo encaja |
|---|---|---|---|---|
| **pgvector** | Self-hosted (extensión Postgres) | ~10–50M con HNSW; más con pgvectorscale | **Joins ACID con datos relacionales** en la misma query | Stack ya con Postgres; búsqueda + datos relacionales |
| **Qdrant** | Self-hosted u open-source + cloud | ~50M con buen rendimiento | Filtrado por metadata best-in-class; velocidad | Read-heavy con filtros complejos |
| **Weaviate** | Self-hosted o gestionado | ~100M | Búsqueda híbrida (BM25 + vector) nativa | Match exacto y semántico conviven |
| **Milvus** | Self-hosted complejo o cloud (Zilliz) | Mil millones o más | Arquitectura distribuida para escala extrema | Catálogos masivos, recommenders consumer |
| **Pinecone** | Totalmente gestionado | ~100M con coste creciente | Zero ops, infraestructura abstraída | Equipo pequeño sin DevOps; coste ingeniería > SaaS |

> Las latencias p50 de las cinco, bien sintonizadas y hasta ~10M vectores, están todas en **5–50 ms.** Las diferencias de QPS publicadas no deciden; deciden los cuatro ejes, en orden: modelo operativo, escala esperada, funcionalidades que de verdad vas a usar, y coste completo.

## 2.3 Por qué el programa elige pgvector

Cuatro razones:

1. **Alineamiento con el stack.** La implementación de referencia usa Ruby on Rails sobre PostgreSQL. El servicio IA habla con el mismo Postgres y aprovecha lo que el equipo ya sabe operar. Qdrant o Pinecone añadirían un sistema nuevo con sus fallos, backups, monitorización y curva.
2. **Joins transaccionales.** El proyecto cruza constantemente búsqueda vectorial con datos relacionales (clientes, sectores, fechas, montos). En pgvector es un `JOIN` + `WHERE` atómico con ACID; en cualquier otra opción es coordinación entre dos sistemas.
3. **Búsqueda híbrida natural.** PostgreSQL tiene `tsvector` y `ts_rank` desde hace décadas: combinar full-text con similitud vectorial es directo, sin *bolt-on*.
4. **Escala esperada.** Cientos a pocos miles de presupuestos × 10–50 chunks = decenas o cientos de miles de vectores. 100k con HNSW corre con latencias de pocos ms. Estamos **dos órdenes de magnitud** por debajo de cualquier techo plausible.

> **Árbol de decisión** (cualquier proyecto): (1) ¿volumen > 50M en 12–18 meses? → Milvus. (2) ¿Postgres ya en el stack / equipo cómodo? → **pgvector** (elección del programa). (3) ¿híbrida central? → Weaviate. (4) ¿sin presupuesto DevOps? → Pinecone; si no → Qdrant.

**Cuándo dejaría de ser correcta:** volumen sostenido > 50M (Qdrant/Milvus); producto predominantemente de match exacto (Weaviate/Elasticsearch); equipo sin experiencia en Postgres pero con presupuesto SaaS (Pinecone); multi-región nativa con SLA estricto (Pinecone/Astra DB); multimodal *first-class* (LanceDB/Marqo).

---

# PARTE 3 — Anatomía de un índice vectorial

> **Para cualquiera:** un índice vectorial evita comparar tu pregunta con todos los vectores. Dos familias clásicas — **partir el espacio en barrios** (IVFFlat) y **navegar un grafo como un GPS** (HNSW) — y una tercera emergente para escalas enormes (DiskANN). Saber cómo funcionan permite elegir parámetros con criterio en vez de copiar defaults.

## 3.1 La línea base: sequential scan (sin índice)

Sin índice, pgvector calcula la distancia query↔cada fila, ordena y devuelve los *k* más cercanos. Recall 100 %, determinista, pero **latencia lineal**: en las decenas de miles de vectores, "interactivo" deja de ser realista. Sigue siendo el *baseline* contra el que mides el impacto de añadir un índice.

## 3.2 IVFFlat — partir el espacio en celdas

> **IVFFlat** = *Inverted File index with Flat vectors.* Agrupa los vectores en "barrios" y solo busca en los barrios cercanos a la consulta.

Analogía: para los 5 restaurantes más cercanos, no comparas con todos los de la ciudad; identificas su **barrio**, miras esos, y amplías si hace falta. Dos fases:

- **Construcción:** un *clustering* (k-means) identifica `lists` centroides ("barrios"). El espacio queda en **celdas de Voronoi**; cada vector se asigna a su celda → "lista invertida" (centroide → vectores de su celda).
- **Consulta:** se calcula la distancia de la query a los `lists` centroides, se eligen los `probes` más cercanos, y la búsqueda se restringe a esas celdas. `probes` ↑ → recall ↑ y latencia ↑.

Parámetros: `lists ≈ sqrt(filas)` (hasta 1M; `filas/1000` por encima) → 100–1000 para el proyecto; `probes ≈ sqrt(lists)` (lists=100 → probes=10).

> **Dos defectos que casi siempre lo descartan en RAG real:** (1) **necesita training** — no puedes crear el índice sobre una tabla vacía (k-means necesita datos representativos); (2) **sufre con datos dinámicos** — al insertar, las celdas dejan de representar la distribución y el recall **se degrada en silencio** hasta que reconstruyes. Para un corpus RAG que crece con cada presupuesto, riesgo operativo concreto.

## 3.3 HNSW — un grafo multicapa como GPS jerárquico

> **HNSW** = *Hierarchical Navigable Small World.* Un grafo en capas que se navega como un GPS: autopista para acercarte, luego carreteras menores, al final calles locales. El viaje resulta **logarítmico**.

La **capa 0** contiene todos los vectores, cada uno conectado a sus vecinos por aristas cortas. Las capas superiores son subconjuntos cada vez más pequeños (~1 % en capa 1, 0.01 % en capa 2…) con aristas largas. La búsqueda va de arriba abajo: entras por la capa más alta, avanzas voraz hacia el vecino más cercano, bajas al estancarte, y en la capa 0 exploras una vecindad amplia para los *k* finales. Es una *skip list* aplicada a grafos (Malkov & Yashunin, 2018): complejidad logarítmica con recall alto incluso en alta dimensión.

**Tres parámetros en pgvector** (dos *build-time*, uno *query-time*):

| Parámetro | Cuándo | Qué controla | Default | Proyecto | Subirlo… |
|---|---|---|---|---|---|
| `m` | build-time (REINDEX para cambiar) | Conexiones máx. por nodo y capa | 16 | **16** | recall ↑ leve, memoria ×2, build ×2 |
| `ef_construction` | build-time | Tamaño lista de candidatos al construir | 64 | **128** | recall ↑ medio, build ↑ |
| `ef_search` | **query-time** (por sesión) | Tamaño lista de candidatos al consultar | 40 | **40** | recall ↑ (curva decreciente), latencia ↑ lineal |

- `m = 16` es donde la comunidad ha convergido para embeddings de 1536 dim (OpenAI). El paper lo nombra el parámetro **más importante**; casi nadie debería cambiarlo sin medir antes que el recall es insuficiente con los demás agotados.
- `ef_construction = 128` (hasta 200) es el punto de partida razonable en 2026. Subirlo duplica el tiempo de construcción, pero se construye una vez y se busca muchas.
- `ef_search` es **el que tuneas empíricamente**: barres entre 10 y 200 sobre queries representativas, mides recall y latencia, eliges el punto que mejor balancea. Bajarlo a ~20 acelera si vas a re-rankear después.

> **Virtudes (opuestas a IVFFlat):** no necesita training (construye sobre tabla vacía e inserta incrementalmente), recall alto (>95 % con defaults), sin degradación silenciosa. **Coste: memoria** — 2–5× más que IVFFlat (guarda el grafo completo además de los vectores). Manejable hasta ~10M vectores en hardware razonable.

```sql
CREATE INDEX chunks_embedding_idx ON chunks
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 128);
-- ef_search se ajusta por sesión:  SET hnsw.ef_search = 40;
```

## 3.4 DiskANN — extiende pgvector más allá de la RAM

> **DiskANN** (Microsoft Research, 2019) = mantiene latencias bajas cuando los vectores ya no caben en RAM. Reemplaza la jerarquía multicapa de HNSW por un **único grafo plano** con aristas largas estratégicas (algoritmo Vamana), cuyo layout en disco minimiza lecturas de SSD.

Una versión cuantizada vive en memoria para navegar rápido; solo el vector completo se lee del SSD para la distancia final. Indexar mil millones de vectores requiere **unos pocos GB de RAM** en lugar de cientos.

En Postgres aparece como **`pgvectorscale`** (Tiger Data, ex-Timescale), `USING diskann`, misma sintaxis y operadores, + cuantización (*Statistical Binary Quantization*). ¿Cuándo migrar de HNSW a DiskANN? Cuando el índice HNSW ya no cabe en `shared_buffers`, o el coste de RAM supera al de SSD. El proyecto está órdenes de magnitud por debajo; se menciona como horizonte y seguimos con HNSW.

## 3.5 Tabla de decisión + operator classes

| Algoritmo | Cuándo gana |
|---|---|
| **Sequential scan** | Hasta pocos miles, datos muy dinámicos, o recall 100 % por auditoría. Baseline. |
| **IVFFlat** | Hasta pocos millones, *mostly-static*, memoria estricta. Analítica batch. Evítalo en RAG que crece. |
| **HNSW** | El caballo de batalla del RAG (decenas de miles a decenas de millones), escrituras activas, recall alto. **Elección del programa.** |
| **DiskANN** (pgvectorscale) | Desde varios millones donde HNSW aprieta la memoria, o decenas de millones donde ya no es viable. |

> **Las tres operator classes** (cruciales): los tres algoritmos comparten `vector_cosine_ops` (coseno, `<=>`), `vector_l2_ops` (L2, `<->`), `vector_ip_ops` (inner product, `<#>`). Al crear el índice eliges **una**, y **solo las queries que usan el operador correspondiente aprovechan el índice.** (Enlaza con el antipatrón de la Parte 4.)

**Verificar que el índice se usa:** `EXPLAIN ANALYZE`. Busca `Index Scan using chunks_embedding_idx` (activo) vs `Seq Scan on chunks` (no se usa). Tres causas habituales: operador desalineado de la operator class, filtros `WHERE` demasiado selectivos, o estadísticas sin actualizar tras la construcción.

---

# PARTE 4 — Diseño del esquema y búsqueda semántica

## 4.1 El modelo relacional: dos tablas, no una

El reflejo de principiante es una única tabla `chunks` con todo dentro. Funciona, pero duplica la metadata del documento en cada chunk (17 chunks → 17 copias del sector/fecha/cliente) y pierde integridad. El modelo correcto es **uno-a-muchos**: `documents` (un presupuesto, una vez) → `chunks` (N fragmentos con su embedding), con `ON DELETE CASCADE` para que borrar un documento borre sus chunks sin lógica aplicativa.

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents (
    id            BIGSERIAL PRIMARY KEY,
    source_path   TEXT NOT NULL,
    document_type VARCHAR(50) NOT NULL,
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata      JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE chunks (
    id          BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_type  VARCHAR(50) NOT NULL,
    content     TEXT NOT NULL,
    embedding   vector(1536),
    metadata    JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

> **JSONB** = tipo de columna de Postgres para guardar datos semiestructurados (campos arbitrarios) y consultarlos.
> **Índice GIN** = *Generalized Inverted Index*; índice invertido que hace rápidas las búsquedas dentro de `JSONB` (y del full-text).

**Cinco decisiones de schema que hay que saber defender:**

1. **Columnas tipadas vs JSONB.** Metadata estable y consultada de forma estructurada (`document_type`, `chunk_type`, fechas) → columnas tipadas (B-tree). Metadata que el chunker enriquece con campos arbitrarios (sector, tecnologías, scope, tags) → `JSONB` (índice GIN). Evita los dos extremos: todo-JSONB (ineficiente) y columna-por-campo (una migración por cada cambio del pipeline).
2. **Índice GIN sobre `metadata`.** Sin él, `WHERE metadata->>'sector' = 'fintech'` hace sequential scan. Coste de mantenimiento bajo al volumen del proyecto, beneficio enorme en filtros.
3. **`vector(1536)`** — dimensionalidad de `text-embedding-3-small`, *hardcodeada* a propósito (cambiarla = re-embeber todo el corpus). Migrar a `text-embedding-3-large` (3072) iría por una **columna nueva**, no modificando la existente.
4. **`embedding` nullable** — permite insertar el chunk y rellenar el vector después. No se usa así en el ejercicio (ingesta atómica), pero deja la puerta abierta a ingesta asíncrona.
5. **Sin índice vectorial todavía** — el esquema omite HNSW a propósito. El directo arranca midiendo `/search` **sin** índice, lo crea, y mide de nuevo: la única forma de aterrizar empíricamente el orden de magnitud que aporta.

## 4.2 Las tres métricas de distancia: coseno, L2, inner product

| Operador | Métrica | Rango | Operator class | Sensible a |
|---|---|---|---|---|
| `<=>` | Distancia **coseno** | 0 a 2 | `vector_cosine_ops` | solo el ángulo |
| `<->` | Distancia **L2** (euclídea) | 0 a ∞ | `vector_l2_ops` | ángulo **y** magnitud |
| `<#>` | **Inner product** negativo | −∞ a 0 | `vector_ip_ops` | ángulo y magnitud |

- **Coseno (`<=>`):** mide el ángulo, ignora la magnitud. Estándar para embeddings de texto de modelos modernos (OpenAI, Cohere, Voyage, Hugging Face), entrenados para que el significado se codifique en la **dirección** del vector, no en su longitud.
- **L2 (`<->`):** distancia en línea recta, sensible a la magnitud. Natural para datos donde la magnitud carga información (coordenadas, sensores, imágenes). Rara vez correcta para texto.
- **Inner product (`<#>`):** producto escalar, devuelto negado porque los operadores de índice de Postgres solo ordenan ascendente y queremos los más similares primero.

> **El caso de OpenAI: embeddings normalizados (|v| = 1).** `text-embedding-3-small` devuelve vectores de norma euclídea 1. Consecuencia: para vectores normalizados, **coseno e inner product producen el mismo orden.** La elección entre `<=>` y `<#>` es indiferente en *qué* chunks recuperas; solo cambia la eficiencia (`<#>` ahorra dividir por las normas, que ya son 1). Aun así el programa usa `<=>` por **convención** (la literatura RAG usa coseno) y **robustez** (si migras a un modelo que no normaliza, la query sigue funcionando).

## 4.3 El antipatrón silencioso que destruye el rendimiento

> **El bug más caro y más fácil de cometer en pgvector.** Si creas un índice HNSW con `vector_cosine_ops`, ese índice **solo** acelera queries con `<=>`. Si la query usa `<->`, el índice **no se activa**: Postgres no emite error ni warning, cae a sequential scan, recalcula L2 contra cada fila, y la latencia pasa de pocos ms a **decenas de segundos** (≈600×–1700× peor). Los resultados siguen correctos en su orden, así que el bug es invisible salvo por la latencia.

> **La regla operativa, sin excepción:** el operador de la query (`<=>`, `<->`, `<#>`) tiene que coincidir con la operator class del índice (`vector_cosine_ops`, `vector_l2_ops`, `vector_ip_ops`).

Pasa cuando copias código de una fuente con otra métrica, cuando el equipo cambia de modelo sin actualizar las queries, o por inercia. **En el proyecto, el índice se crea con `vector_cosine_ops` y todas las queries usan `<=>`.**

## 4.4 La query completa: tres capas en una sentencia atómica

Casi nadie quiere "los *k* más cercanos" sin más, sino "los *k* más cercanos **del sector fintech, de los últimos 24 meses, con monto entre 50k y 200k**". pgvector lo resuelve en **una query SQL atómica** con búsqueda semántica + filtros relacionales + filtros JSONB + joins:

```sql
SELECT c.id, c.content, c.chunk_type,
       c.embedding <=> :query_vector AS distance,
       d.metadata->>'sector' AS sector, d.ingested_at
FROM chunks c
JOIN documents d ON d.id = c.document_id
WHERE d.metadata->>'sector' = 'fintech'
  AND d.ingested_at > NOW() - INTERVAL '24 months'
  AND (d.metadata->>'budget')::numeric BETWEEN 50000 AND 200000
ORDER BY c.embedding <=> :query_vector
LIMIT 5;
```

Esto es lo que un RAG sobre datos empresariales necesita y lo que **Pinecone, Qdrant o Weaviate no pueden hacer sin coordinar con otro sistema.** Es la razón principal por la que pgvector es correcto para el programa, y la propiedad que más echarás en falta el día que migres a un dedicado por escala.

> **`hnsw.iterative_scan` (pgvector 0.8):** cuando los filtros del `WHERE` son muy selectivos (dejan pocas filas), HNSW tiene dificultades porque está optimizado para encontrar los *k* vecinos en el conjunto completo, no en un subconjunto pre-filtrado. `iterative_scan` expande la búsqueda iterativamente hasta cumplir el `LIMIT`. Se activa y se mide en el directo.

**Diagnóstico correcto** cuando una query semántica funciona pero va inexplicablemente lenta: **`EXPLAIN ANALYZE` primero**, antes de asumir nada. Es la diferencia entre un equipo que produce RAGs performantes y uno que pelea con latencias misteriosas durante semanas.

---

# PARTE 5 — Del prototipo a producción

> **Para cualquiera:** el sistema del ejercicio funciona, pero es **de desarrollo**: Docker local, defaults de Postgres para un demo, sin índice, sin métricas, sin mantenimiento. Esta parte cubre lo que separa "funciona en la sesión" de "funciona en producción dos años sin sobresaltos". No se aplica al ejercicio (los volúmenes no lo requieren), pero es lo que argumentarás el día que lleves pgvector a producción.

## 5.1 Sizing de memoria: la regla que gobierna todo

> **El 80 % del rendimiento de pgvector + HNSW se determina por una sola variable: si el índice cabe en memoria o no.** Todo lo demás (`ef_search`, parámetros de construcción, modelo, hardware) son refinamientos.

Si el índice vive en `shared_buffers` + cache del SO, las queries son de pocos ms. Si no cabe y Postgres lee páginas de disco en cada consulta, **ningún parámetro recupera la latencia.** Es estructural: HNSW es un grafo; una búsqueda salta entre nodos. Cada salto en RAM son ~5 µs; desde SSD, ~100 µs. Con ~30 saltos por query, ~3 ms solo de I/O — sin contar distancias ni red. Si el SSD está ocupado, la cola añade el "long tail" que ningún tuning arregla.

**Sizing práctico (tres componentes):**
- **Vectores en disco:** `text-embedding-3-small` = 1536 × 4 bytes ≈ **6 KB/vector.** 1M chunks ≈ 6 GB.
- **Índice HNSW:** ≈ **2–3×** los vectores con `m=16`. 1M chunks → 12–18 GB.
- **Overhead de Postgres:** connection pools, `work_mem`, OS/WAL buffers.
- **Regla conservadora:** RAM total ≥ **1.5 × (índice + vectores).**

**Tres parámetros de PostgreSQL** (en `postgresql.conf` o flags del contenedor):

| Parámetro | Qué es | Default | Producción (server 32 GB) |
|---|---|---|---|
| `shared_buffers` | Memoria que Postgres reserva para su cache | 128 MB | **8 GB** (25 % RAM) |
| `effective_cache_size` | Pista al planner sobre memoria total disponible (no asigna) | 4 GB | **24 GB** (75 % RAM) |
| `work_mem` | Memoria por operación (sort, hash join) | 4 MB | **64–256 MB** |

```yaml
# docker-compose (server con 32 GB RAM)
postgres -c shared_buffers=8GB -c effective_cache_size=24GB \
         -c work_mem=64MB -c maintenance_work_mem=2GB
```

> El fallo más común en migraciones pgvector→producción: la latencia que en pruebas era de 5 ms pasa a 500 ms porque el índice ya no entra en memoria.

## 5.2 Construcción del índice: parámetros distintos a los de la query

`CREATE INDEX ... USING hnsw` es una operación masiva con sus propios parámetros:

- **`maintenance_work_mem`** — el más importante. Memoria para operaciones de mantenimiento de índices. Default 64 MB = **trágico** para HNSW: si el grafo en construcción no cabe, Postgres cae a construcción en disco **10×–50× más lenta.** Para 5M vectores necesitas 8–16 GB. `SET maintenance_work_mem = '4GB'` antes de construir.
- **`max_parallel_maintenance_workers`** — workers paralelos para construir. Default 2. Con 4, un índice de 1M filas que en serie tarda 30 min se construye en 8–10 min. Techo = vCPUs. (En docker-compose declara `shm_size` suficiente, o los workers crashean con OOM al final.)
- **`CONCURRENTLY`** — crítico en producción. Sin él, `CREATE INDEX` bloquea la tabla para escrituras durante toda la construcción. Con él es más lento (1.5×–2×) pero la tabla sigue aceptando ingestas. **En desarrollo opcional; en producción obligatorio.**

```sql
SET maintenance_work_mem = '4GB';
SET max_parallel_maintenance_workers = 4;
CREATE INDEX CONCURRENTLY chunks_embedding_idx ON chunks
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 128);
```

**Cifras de referencia** (Postgres + pgvector 0.8, HNSW m=16/ef_construction=128, 1536 dim):

| Volumen | Tamaño índice | Build time | p95 query |
|---|---|---|---|
| 100K vectores | ~1 GB | < 2 min | 2–5 ms |
| 1M vectores | ~8 GB (3 GB con halfvec) | 20–30 min | 8–15 ms |
| 5M vectores | ~40 GB (15 GB con halfvec) | 2–3 h | 20–40 ms |

> El proyecto vive en la primera fila. Las filas siguientes justifican `halfvec`.

## 5.3 halfvec: la cuantización que ahorra la mitad del almacenamiento

> **halfvec** (pgvector 0.7) = guarda cada dimensión del embedding en **16 bits** en vez de 32. Espacio a la mitad, construcción a la mitad, y recall sobre embeddings normalizados de OpenAI **> 99 %** (indistinguible de float32).

Los embeddings se guardan por defecto como floats de 32 bits (4 bytes/dim) — lo que usa `vector(1536)`. Es **mucha más precisión de la que la búsqueda semántica necesita.** halfvec no es cuantización agresiva como la binaria (1 bit/dim, degrada recall); es una pérdida de precisión imperceptible para la inmensa mayoría de casos.

```sql
-- La columna sigue siendo vector(1536); se cuantiza en el índice:
CREATE INDEX chunks_embedding_idx ON chunks
  USING hnsw ((embedding::halfvec(1536)) halfvec_cosine_ops)
  WITH (m = 16, ef_construction = 128);
```

El cast `embedding::halfvec(1536)` cuantiza en memoria al construir, sin tocar la columna. Las queries siguen usando `<=>` sin cambios. **Recomendación 2026: empieza con halfvec desde el día uno si vas a producción** — migrar `vector`→`halfvec` con decenas de millones cargados es doloroso. (El ejercicio no lo usa por mantener el setup mínimo; es lo primero que añadirías al pasar a producción.)

## 5.4 Monitorización operativa

Tres preguntas que deberías poder contestar en cualquier momento:

- **¿Se está usando el índice?** La vista `pg_stat_user_indexes`: `idx_scan` (cuántas veces se usó), `last_idx_scan` (PG16+).
  ```sql
  SELECT indexrelname AS index_name, idx_scan AS scans, last_idx_scan AS last_used,
         pg_size_pretty(pg_relation_size(indexrelid)) AS size
  FROM pg_stat_user_indexes WHERE relname = 'chunks' ORDER BY idx_scan DESC;
  ```
  Si tu índice vectorial principal tiene `idx_scan = 0` tras un periodo en producción, casi siempre es el **antipatrón** de la Parte 4. La forma más rápida de detectar el bug silencioso.
- **¿Cuánto tarda cada query?** `pg_stat_statements` (stats agregadas por query: llamadas, tiempo total/medio/min/max). Habilítalo desde el día 1. El plugin **Logfire** (ya en el stack del programa) también lo captura, integrándolo con las trazas de las llamadas al LLM → visión *end-to-end*.
- **¿Se está degradando el índice?** Por **bloat** (updates/borrados dejan páginas muertas) o **estadísticas obsoletas** (el planner decide subóptimo). Ciclo de mantenimiento:
  - `VACUUM ANALYZE chunks` — recupera espacio muerto + actualiza estadísticas.
  - `REINDEX INDEX CONCURRENTLY chunks_embedding_idx` — reconstruye el índice (recupera rendimiento tras bloat; `CONCURRENTLY` no bloquea queries).
  - `ANALYZE chunks` — solo estadísticas; rápido y barato.
  - **Cadencia (escrituras moderadas):** ANALYZE automático (autovacuum), `VACUUM ANALYZE` semanal en ventana de bajo tráfico, `REINDEX CONCURRENTLY` mensual o cuando notes degradación. Escrituras intensas → acelera proporcionalmente.

## 5.5 Las tres señales objetivas de migración

pgvector es correcto para el programa y para la mayoría del RAG en producción 2026. **Tres señales medibles** (no preferencias) indican que llegaste a su techo y conviene evaluar un dedicado (Qdrant, Milvus) o pgvectorscale/DiskANN:

1. **El índice HNSW ya no cabe en RAM.** Si `tamaño_índice / RAM_disponible > ~70 %`, la p99 se vuelve impredecible. Corto plazo: más RAM. Medio plazo: pgvectorscale/DiskANN.
2. **La p99 supera tu SLO de forma sostenida.** Si las queries vectoriales superan el umbral tolerable (típicamente 100–200 ms para RAG interactivo) y ya descartaste tuning, antipatrones y bloat, es el techo de pgvector para tu volumen. Un dedicado da 2×–5× mejor p99 a igual hardware.
3. **Necesitas funcionalidades nativas que pgvector no tiene.** Multimodal *first-class*, sharding multi-región con SLA estricto, modelos de coste muy específicos. Destinos: multimodal → LanceDB/Marqo; multi-región → Pinecone/Astra DB; híbrida BM25 → Weaviate; soberanía → cualquier self-hosted.

> **La regla final:** si **ninguna** de las tres se cumple, mantener pgvector es casi siempre lo correcto — aunque tengas la tentación de migrar a algo "más serio". La complejidad operativa de un dedicado tiene su propio coste y solo se justifica cuando las señales lo exigen.

---

## Cómo conecta con nuestro ejercicio y con el directo

El **ejercicio previo** ([`session-08.md`](session-08.md)) cubre la **primera mitad** del arco: construir el sistema que **persiste, indexa el esquema y consulta** — las dos tablas, la ingesta transaccional, el endpoint `/search` por distancia coseno — **deliberadamente sin índice vectorial.**

La **sesión en vivo** cubre la otra mitad: **añadir el índice HNSW y medir su impacto** contra el *baseline* de sequential scan, comparar las tres métricas de distancia sobre el corpus, construir **búsqueda híbrida** (full-text + vector), explorar **filtros por metadata** comparando planes de ejecución, y aplicar el tuning de la Parte 5. La Sesión 9 empieza el **RAG propiamente dicho**: integrar este retriever con el generador.

### Chuleta de una página (lo imprescindible)

- **Por qué existen:** la similitud en alta dimensión es un problema distinto al de igualdad exacta; un B-tree no lo resuelve. Una BBDD vectorial = **índices ANN + persistencia.**
- **KNN vs ANN:** exacto (100 % recall, lineal) vs aproximado (~98 %, logarítmico). El recall **se mide**; los resultados **no son deterministas.**
- **Cuándo:** <10K = array; **10K–50M = BBDD vectorial** (aquí cae el proyecto); >50M = distribuido. Sin similitud semántica, full-text basta.
- **Mercado:** pgvector (Postgres + ACID), Qdrant (velocidad/filtros), Weaviate (híbrida), Milvus (escala extrema), Pinecone (zero ops). **Programa → pgvector** por alineamiento de stack, joins ACID, híbrida natural y escala.
- **Índices:** IVFFlat (celdas; necesita training, sufre con inserts) · **HNSW** (grafo; `m=16`, `ef_construction=128`, `ef_search=40`; sin training, +memoria) · DiskANN (horizonte, >RAM).
- **Esquema:** 2 tablas (`documents` 1→N `chunks`, CASCADE); estable→columnas, flexible→JSONB+GIN; `vector(1536)` fijo; sin índice aún.
- **Distancia:** texto normalizado → **coseno `<=>` + `vector_cosine_ops`**. El **operador de la query debe coincidir con la operator class del índice**, o cae a seq scan **en silencio.**
- **Producción:** la regla del 80 % = **¿el índice cabe en RAM?** (RAM ≥ 1.5×(índice+vectores)). Tunea `shared_buffers`/`maintenance_work_mem`; usa `CREATE INDEX CONCURRENTLY`; **halfvec** (−50 % espacio, recall >99 %). Monitoriza `pg_stat_user_indexes` + `pg_stat_statements`; mantén con VACUUM/REINDEX/ANALYZE. **Migra solo si** el índice no cabe en RAM, la p99 supera el SLO, o necesitas funciones nativas que pgvector no tiene.
