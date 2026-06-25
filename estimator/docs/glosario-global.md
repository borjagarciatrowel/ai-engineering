# Glosario global de términos

> Glosario único de todo el programa AI Engineering, compilado a partir de los documentos de teoría (versión clara) de las Sesiones 1–10.
> **Cómo está ordenado:** agrupado por dominio y ordenado siguiendo la progresión del programa (fundamentos → CAG → producto → datos → embeddings → BBDD vectoriales → RAG). Cada término se define **una sola vez**, en el grupo donde mejor encaja.
> **Cómo leerlo:** de corrido la primera vez; después, como referencia (Ctrl-F por el término).

**Índice de grupos**

1. [Fundamentos: LLMs, tokens y APIs](#1-fundamentos-llms-tokens-y-apis)
2. [Arquitectura: CAG vs RAG](#2-arquitectura-cag-vs-rag)
3. [Producto: wrappers, streaming, caché y observabilidad](#3-producto-wrappers-streaming-cache-y-observabilidad)
4. [Prompts, salida estructurada y validación](#4-prompts-salida-estructurada-y-validacion)
5. [Guardrails, seguridad y privacidad](#5-guardrails-seguridad-y-privacidad)
6. [Contexto dinámico, agentes y evaluación](#6-contexto-dinamico-agentes-y-evaluacion)
7. [Datos: ingesta, parsing y calidad](#7-datos-ingesta-parsing-y-calidad)
8. [Embeddings, similitud y chunking](#8-embeddings-similitud-y-chunking)
9. [Bases de datos vectoriales e índices](#9-bases-de-datos-vectoriales-e-indices)
10. [RAG: recuperación (básica y avanzada)](#10-rag-recuperacion-basica-y-avanzada)
11. [Infraestructura web, API y concurrencia (transversal)](#11-infraestructura-web-api-y-concurrencia-transversal)

---

## 1. Fundamentos: LLMs, tokens y APIs
*(Sesión 1–2)*

| Término | Definición |
|---|---|
| **LLM** (*Large Language Model*) | Modelo de lenguaje: recibe texto y devuelve texto prediciendo qué fragmento viene a continuación. Su conocimiento se congela en el entrenamiento (tiene fecha de corte). |
| **Inferencia** | El momento en que el modelo *responde* a una petición (no cuando se entrena). |
| **Stateless (sin memoria)** | El modelo **no recuerda** la conversación; para que "recuerde", reenvías todo el historial en cada llamada. |
| **Token** | Unidad mínima en que el modelo trocea el texto (≈ ¾ de palabra). **Todo se factura por tokens → los tokens son dinero.** |
| **Tokenización** | El proceso que convierte texto en una secuencia de IDs numéricos (y viceversa). Los modelos no leen texto: un *transformer* solo opera sobre enteros. |
| **BPE** (*Byte Pair Encoding*) | El algoritmo de tokenización de casi todos los LLMs actuales (GPT, Llama, Mistral…). |
| **Ventana de contexto** | Máximo de tokens en una sola llamada. Incluye **todo**: system prompt + historial + entrada del usuario + **la respuesta del modelo**. |
| **Latencia** | Cuánto tarda en responder. El coste que más nota el usuario. (Término transversal a todo el programa.) |
| **Prompt** | El texto completo que se envía al modelo (instrucciones + contexto + pregunta). |
| **System prompt** | Las instrucciones del desarrollador que fijan el rol y comportamiento del asistente; el usuario final no las ve. |
| **Role** | Etiqueta de cada mensaje (`system` / `user` / `assistant`) que dice quién habla y cómo interpretarlo. |
| **Temperature** | El mando de aleatoriedad: `0.0` = determinista (lo más probable); alto = más creativo. |
| **`max_tokens`** | Límite de tokens de la respuesta. En Anthropic (Messages API) es **obligatorio**. |
| **Modelo de razonamiento** | Generación que "piensa" antes de responder: más calidad, menos control sobre algunos ajustes, y ese pensamiento se factura. |
| **`finish_reason` / `stop_reason`** | Por qué terminó la respuesta (`stop` = normal, `length` = se cortó por límite de tokens…). |
| **API** | La puerta para usar el modelo desde tu código: envías una petición por internet y recibes la respuesta. |
| **SDK** | La librería oficial del proveedor que envuelve esas llamadas HTTP (`openai`, `anthropic`, `google-genai`). |
| **Responses API** (OpenAI) | API moderna (marzo 2025): interfaz limpia, herramientas integradas, estado entre turnos. **Recomendada para proyectos nuevos.** |
| **Chat Completions API** (OpenAI) | La API anterior; aún soportada. Su estructura `messages` con roles es el patrón que comparten casi todos los demás proveedores. |
| **Messages API** (Anthropic) | La única API de Anthropic; el system prompt va en parámetro separado y `max_tokens` es obligatorio. |
| **Google Gen AI SDK** (`google-genai`) | SDK unificado de Gemini. Funciona con la Developer API (solo una key) o con Vertex AI (vía Google Cloud). |
| **`count_tokens()`** | Endpoint **gratuito** de Gemini para estimar el consumo *antes* de enviar. Ni OpenAI ni Anthropic lo ofrecen como endpoint nativo. |

---

## 2. Arquitectura: CAG vs RAG
*(Sesión 2, 6, 9)*

| Término | Definición |
|---|---|
| **CAG** (*Cache/Context-Augmented Generation*) | Meter **todo** el conocimiento relevante en el prompt, precargado, sin búsqueda. |
| **RAG** (*Retrieval-Augmented Generation*) | **Buscar** los documentos relevantes en cada pregunta; solo esos van al prompt. |
| **Retrieval (recuperación)** | El paso de buscar y traer los documentos/chunks relevantes antes de llamar al modelo. |
| **KV-cache** | Representaciones intermedias de la atención (claves/valores) precomputadas para el contexto fijo, para no reprocesarlo en cada llamada. Hace barato precargar mucho conocimiento estático (clave del CAG). |
| **Grounding** | Obligar al modelo a apoyarse **solo** en el contexto recuperado, no en su conocimiento general. |
| **Fine-tuning** | Reentrenar el modelo con datos propios. **No sustituye a RAG**: es una capa encima, cuando el retrieval no basta (estilo propio, terminología, formato). |
| **Contexto estático** | Lo que el equipo escribió de antemano y no cambia entre peticiones (templates, ejemplos del prompt). |
| **Contexto dinámico** | Lo que el sistema busca en el momento porque depende de lo que el usuario pidió (un PDF, precios de hoy, datos de la BBDD). |
| **Historial conversacional** | El array **bruto y cronológico** de mensajes que viaja a la API en cada llamada. Responde *"¿qué dijo en el turno 7?"*. |
| **Memoria conversacional** | Los **hechos destilados** que el sistema ha aprendido ("el equipo son 3 personas"). Persiste aunque el turno original se descarte. Responde *"¿qué sabemos del proyecto?"*. |
| **Estrategias de historial** | **Ventana deslizante** (últimos N turnos) · **Resumen acumulativo** (resume lo antiguo) · **Híbrida con anclas** (resumen + ventana + turnos críticos que nunca se descartan). |

---

## 3. Producto: wrappers, streaming, caché y observabilidad
*(Sesión 3, parte de la 4)*

| Término | Definición |
|---|---|
| **Wrapper / capa de abstracción** | Código intermedio que unifica el acceso a varios proveedores de LLM; el proveedor pasa a ser **configuración**. |
| **Proveedor** | Quien sirve el modelo: OpenAI, Anthropic, Google, etc. |
| **Fallback** | Rotar automáticamente a otro proveedor cuando el primero falla. |
| **Endpoint** | Una URL del backend (p. ej. `/estimate`) que recibe una petición y devuelve una respuesta. |
| **LiteLLM** | Librería open source con interfaz compatible para **+100 modelos de +10 proveedores**; solo estandariza la llamada (no impone chains ni agents). |
| **OpenRouter** | Un mercado de modelos: una sola API key da acceso a decenas de modelos vía API unificada, con routing y facturación consolidada. |
| **LangChain** | Framework de orquestación de LLMs (chains, agents, memoria, tools); incluye abstracción de proveedores como una parte. |
| **Instructor** | Librería que toma tu modelo Pydantic, detecta el proveedor y empaqueta la llamada con el mecanismo correcto; te devuelve siempre una instancia tipada. |
| **Streamlit / Gradio / Chainlit** | Frameworks de UI: dashboards de datos con chat / envolver cualquier función Python en una web / UI específica para apps conversacionales con LLMs. |
| **Streaming** | Enviar la respuesta por fragmentos según se genera, no de golpe al final. |
| **StreamingResponse / chunked transfer** | FastAPI manda la respuesta en trozos (`Transfer-Encoding: chunked`, sin `Content-Length`) desde un **generador async**. |
| **SSE** (*Server-Sent Events*) | Eventos estructurados servidor→cliente (`data`, `event`, `id`); el navegador tiene API nativa (`EventSource`). Unidireccional. |
| **WebSocket** | Canal **bidireccional** persistente cliente↔servidor; empieza con un handshake HTTP (`Upgrade`) y luego abandona HTTP. |
| **Caché** | Guardar una respuesta ya calculada para no recalcularla ni volver a pagarla. |
| **Cache exact-match** | Devuelve la respuesta solo si la clave (el texto) es idéntica **carácter a carácter**. |
| **Cache semántico** | Compara **significados** (embeddings), no strings, para reconocer peticiones equivalentes. |
| **HIT / MISS** | HIT = el cache tenía la respuesta y la reutiliza; MISS = no la tenía y hay que calcularla. |
| **Threshold (umbral)** | El corte de similitud a partir del cual consideras que dos inputs son "el mismo". |
| **Bucket** | Cajón del cache que agrupa requests con los mismos parámetros estructurales; dentro de él, el threshold puede ser más agresivo. |
| **TTL** (*Time To Live*) | Cuánto vive una entrada de caché antes de expirar (estimador: 24 h; datos en vivo: minutos). |
| **Invalidar** | Decidir cuándo una entrada de caché ya no es válida. |
| **Redis / `redisvl`** | BBDD en memoria muy rápida / librería sobre Redis con índices vectoriales y una clase `SemanticCache` lista para usar. |
| **Observabilidad** | Saber qué pasó cuando algo falla (qué prompt se envió, cuánto costó, qué latencia tuvo). |
| **Structured logging** | Registrar logs como **objetos con campos tipados** (JSON), parseables por máquinas, en vez de texto plano. |
| **structlog** | La librería de structured logging más madura de Python; filosofía *"los logs son datos, no strings"*. |
| **Pydantic Logfire** | Herramienta de observabilidad del equipo de Pydantic, construida sobre OpenTelemetry. |
| **OpenTelemetry** | Estándar abierto de observabilidad (trazas, métricas, logs). |
| **Span** | Unidad de trabajo medida dentro de una traza. |

---

## 4. Prompts, salida estructurada y validación
*(Sesión 4)*

| Término | Definición |
|---|---|
| **Jinja2** | El motor de plantillas de Python: un texto con huecos (`{{ variable }}`) y condicionales que se rellenan en tiempo de ejecución. |
| **f-string** | Cadena de Python que interpola variables directamente (`f"...{variable}..."`). |
| **Template (plantilla)** | La estructura fija del prompt con huecos para las variables; versionada en el repositorio (`.j2`). |
| **Few-shot** | Incluir en el prompt unos pocos ejemplos de entrada→salida correcta para que el modelo imite el patrón. |
| **XML tags / Markdown (en prompts)** | Delimitar las secciones del prompt con `<contexto>...</contexto>` (estilo Anthropic) o con encabezados `## Contexto` (estilo OpenAI). |
| **Schema** | La descripción formal de la forma que deben tener unos datos: qué campos, qué tipos, qué es obligatorio. |
| **Pydantic** | Librería de Python para definir esos schemas como clases y validar datos contra ellos. |
| **JSON Schema** | Estándar para describir la forma de un JSON; Pydantic lo genera solo a partir de una clase. |
| **`model_validator`** | Método de Pydantic para validaciones custom (reglas de negocio que el schema no expresa solo, p. ej. que las fases sumen el total). |
| **Structured Outputs** | El modo nativo de OpenAI que **garantiza** que la respuesta cumple un schema. |
| **Tool use forzado** | Obligar a Anthropic a "llamar a una herramienta" cuyo formato de entrada es justo el schema que quieres (mismo resultado que Structured Outputs). |
| **UI generativa** | El LLM no escribe texto sino que escoge **qué componente de la UI renderizar y con qué datos** (popularizado por Vercel AI SDK 3.0). |
| **Autonomía parcial** | El modelo hace el trabajo pesado pero el humano revisa y confirma a través de la interfaz, en vez de delegar todo a ciegas. |
| **Antipatrón** | Una solución que parece la obvia pero que, a la larga, causa más problemas de los que resuelve. |

---

## 5. Guardrails, seguridad y privacidad
*(Sesión 4, 6)*

| Término | Definición |
|---|---|
| **Guardrail (barrera)** | Una comprobación que valida lo que entra o sale del sistema y decide qué hacer si algo está mal. |
| **Defensa en profundidad** | Varias capas de validación encadenadas; ninguna lo cubre todo, pero juntas sí. |
| **Prompt injection** | Texto del usuario diseñado para secuestrar las instrucciones del modelo. |
| **PII** | Datos personales identificables (nombres, emails, teléfonos, salarios). |
| **Alucinación** | Información inventada que el modelo presenta como si fuera real. |
| **Moderation API** | Servicio de OpenAI que clasifica un texto en categorías de contenido tóxico con un *score* por categoría. |
| **LLM-as-judge** | Usar un segundo LLM (más barato) para juzgar si una respuesta es correcta o coherente. Modos: **pointwise** (puntúa 0–1) y **pairwise** (compara dos respuestas). |
| **Guardrails AI** | Librería con un catálogo de validadores listos (PII, toxicidad, citas inventadas…). |
| **Políticas de fallo** | Qué hacer cuando un guardrail salta: **`exception`** (aborta con error), **`fix · retry`** (reintenta con corrección), **`filter`** (degrada a un resultado seguro). |
| **GDPR** | El reglamento europeo del tratamiento de datos personales (incluye el derecho al olvido, art. 17). |
| **Anonimización vs pseudonimización** | Borrar el dato vs sustituirlo por un seudónimo coherente. En RAG **gana pseudo**, porque mantiene la semántica del texto. |
| **Presidio** | Librería de Microsoft para detectar y anonimizar PII. |
| **Faker** | Librería que genera datos ficticios realistas (nombres, emails, empresas). |
| **Mapping table** | Tabla que registra cada sustitución (original → pseudónimo) para poder revertirla; sostiene el derecho al olvido. |
| **Filtración semántica** | Las formas en que un RAG puede filtrar datos sensibles aunque haya control de acceso: **directa** (el dato está literal), **por agregación** (combinar queries inocuas) y **por inferencia** (deducir del contexto que rodea, incluso tras anonimizar). |

---

## 6. Contexto dinámico, agentes y evaluación
*(Sesión 5)*

| Término | Definición |
|---|---|
| **Function calling / tool** | Darle al LLM una "herramienta" que puede invocar (buscar en web, llamar a una API); el LLM decide cuándo usarla. |
| **Agentic loop** | El ciclo razonar → invocar tool → recibir resultado → razonar de nuevo, hasta dar la respuesta final. |
| **Actor / Critic / Boss** | Patrón multi-rol: generador / evaluador-verificador / orquestador (Anthropic *Building Effective Agents*; *Self-Refine*; *Reflexion*). |
| **Tier** | El perfil del usuario (developer / pm / executive) que decide qué *experiencia* recibe, no qué *puede hacer*. |
| **Golden dataset** | Conjunto curado de casos de prueba, cada uno con su criterio de éxito anotado a mano. |
| **Coeficiente de variación (CV)** | Desviación estándar / media; mide la variabilidad relativa (se acepta hasta ~25%). |
| **DeepEval / `GEval`** | Framework de evaluación de LLMs sobre pytest; su métrica `GEval` encapsula el LLM-as-judge. |

---

## 7. Datos: ingesta, parsing y calidad
*(Sesión 6)*

| Término | Definición |
|---|---|
| **Corpus** | El conjunto de documentos sobre el que trabaja el sistema. |
| **Document (canónico)** | Objeto único que produce la ingesta para el resto del servicio: **contenido textual + metadatos**. (En la literatura: Document / Chunk / Passage.) |
| **Chunk** | Un trozo de documento (un párrafo, una sección). Se indexan **chunks, no documentos enteros**. |
| **Metadatos** | Datos *sobre* el documento que no están en su texto: origen, fecha, autor, sector, sensibilidad. Sirven para filtrar y citar. |
| **Trazabilidad** | Poder citar de qué fuente concreta sale cada afirmación. |
| **Linaje** (*lineage*) | El rastro del origen y las transformaciones de un dato. En RAG es **condición de utilidad**, no lujo. |
| **Context erosion** | La pérdida progresiva de contexto a medida que el dato se mueve entre sistemas. |
| **Pipeline** | La cadena de pasos por los que pasa un dato o una consulta. **Offline** (ingest→parse→chunk→embed, en background) y **online** (retrieve→augment→generate, síncrono); no se mezclan. |
| **Loaders / Parsers / Normalizers** | Las 3 capas de ingesta: *cómo llego al fichero* (paths, S3, Drive) → *qué hay dentro* (elige librería por formato) → *cómo lo paso al `Document` canónico*. |
| **`unstructured`** | Librería cuyo `partition()` detecta el formato y devuelve elementos heterogéneos (`Title`, `NarrativeText`, `Table`…) con metadatos de localización. |
| **Pandera** | Lo que Pydantic es a un objeto, pero para **DataFrames**: valida un DataFrame columna a columna y reporta qué filas fallan y por qué. |
| **Reparar / cuarentena / descartar** | Las 3 políticas ante datos sucios: arreglar sin pérdida semántica / preservar aparte para revisión humana / eliminar con log detallado. |
| **Lost in the middle** | La información en la mitad del contexto se recupera peor que en los extremos (curva en U, cae hasta 20 puntos; Liu et al. 2023). No es artefacto de una arquitectura. |

---

## 8. Embeddings, similitud y chunking
*(Sesión 7)*

| Término | Definición |
|---|---|
| **Embedding** | Función que convierte un texto en un **vector de números de dimensión fija**; textos parecidos → vectores cercanos. |
| **Vector / espacio Rⁿ** | El embedding es un punto en un espacio de muchas dimensiones; "cercanía" ahí ≈ parecido de significado. |
| **Dimensiones** | Cuántos números tiene el vector (384, 1536, 3072…). Más dims = más capacidad, pero más bytes y latencia. |
| **Aprendizaje contrastivo** | Entrenar con tripletes "esto se parece, esto no" millones de veces, hasta que el modelo coloca lo parecido junto. |
| **Búsqueda semántica** | Buscar por **significado** (vectores cercanos), no por coincidencia literal de palabras. |
| **Similitud coseno** | Mide el **ángulo** entre dos vectores (−1 a 1), insensible a la magnitud. La métrica más común para texto. |
| **Producto escalar (dot product)** | El numerador del coseno; idéntico al coseno si los vectores están normalizados, pero más barato. |
| **Distancia euclidiana** | Distancia recta entre vectores; para vectores normalizados **ordena igual** que el coseno. |
| **Normalización** | Llevar un vector a longitud 1. Muchas BBDD lo asumen; si truncas un vector, hay que renormalizar. |
| **MTEB** | *Massive Text Embedding Benchmark*: referencia de facto, pero mide promedios generalistas (no es filtro único). |
| **Matryoshka (MRL)** | Entrenamiento que guarda lo importante en las primeras dimensiones, así puedes **truncar** el vector a menos dims sin re-entrenar y casi sin perder calidad. |
| **Model card** | La ficha oficial de un modelo: cómo se entrenó, qué métrica usar, sus límites. |
| **Maldición de la dimensionalidad** | En muchas dimensiones las distancias se concentran; por eso una similitud 0.2–0.5 entre textos no relacionados es **normal**. |
| **Chunking** | Partir documentos en trozos antes de embederlos. La decisión de **mayor impacto** en la calidad del retrieval. |
| **Overlap** | Solapamiento entre chunks consecutivos (típico 10–20%) para no perder ideas en las fronteras. |
| **Contextual chunk header** | Info del documento padre añadida (prepended) al chunk antes de embederlo (alto ROI). |
| **Contextual Retrieval** | Técnica de Anthropic: enriquecer cada chunk con un párrafo de contexto generado por un LLM antes de embederlo. |
| **Topic-based segmentation** | Chunking semántico: parte donde la similitud entre frases vecinas cae bajo un umbral → chunks que coinciden con bloques temáticos. |
| **BM25 / TF-IDF** | Métricas clásicas de búsqueda por **términos exactos**, pesando los raros más que los comunes. Complementan a los embeddings (búsqueda híbrida). |

---

## 9. Bases de datos vectoriales e índices
*(Sesión 8)*

| Término | Definición |
|---|---|
| **Base de datos vectorial** | Almacén que guarda embeddings y permite buscar los más parecidos (infraestructura de RAG). |
| **pgvector** | La extensión que convierte PostgreSQL en base de datos vectorial, sin añadir un sistema nuevo. |
| **KNN exacto** | Comparar la consulta contra **todos** los vectores. Siempre acierta, pero el coste crece con el nº de vectores. |
| **ANN aproximado** | Estructuras (grafos, particiones) que miran **solo unos pocos** vectores prometedores. Acepta fallar de vez en cuando a cambio de ser mucho más rápido. |
| **Recall** | De todo lo relevante que existe, cuánto trajiste. Con ANN, ~95–99%. |
| **Índice vectorial** | El "truco" (IVFFlat, HNSW, DiskANN) que evita comparar contra todos los vectores. |
| **Índice B-tree** | El índice clásico relacional; aprovecha que los valores son **ordenables** (números, fechas, texto). No sirve para vectores. |
| **IVFFlat** (*Inverted File, Flat*) | Agrupa los vectores en "barrios" y solo busca en los cercanos a la consulta. Bueno *mostly-static*; evítalo en RAG que crece. |
| **HNSW** (*Hierarchical Navigable Small World*) | Grafo en capas que se navega como un GPS (autopista → calles locales); búsqueda **logarítmica**. El caballo de batalla del RAG. |
| **DiskANN** | Grafo plano (algoritmo Vamana) que mantiene baja latencia cuando los vectores ya no caben en RAM. |
| **JSONB** | Tipo de columna de Postgres para guardar datos semiestructurados y consultarlos. |
| **Índice GIN** (*Generalized Inverted Index*) | Índice invertido (término → documentos) que acelera las búsquedas en JSONB y full-text. |
| **halfvec** | Tipo de pgvector que guarda cada dimensión en **16 bits** (mitad de espacio); recall >99% sobre embeddings normalizados de OpenAI. |
| **QPS** (*queries per second*) | Consultas por segundo que aguanta el sistema. |
| **Self-hosted vs managed** | Lo gestionas tú (control total, pero updates/backups/guardias) o el proveedor (pagas por no pensar, menos control, coste que escala con el uso). |
| **ACID** | Garantías transaccionales: una operación se completa entera o se revierte entera (nunca a medias). |
| **Qdrant / Weaviate / Milvus / Pinecone** | Otras BBDD vectoriales: filtrado por metadata best-in-class / híbrida BM25+vector nativa / escala extrema distribuida / totalmente gestionada (zero-ops). |

---

## 10. RAG: recuperación (básica y avanzada)
*(Sesión 9, 10)*

### 10.1 Recuperación básica *(Sesión 9)*

| Término | Definición |
|---|---|
| **Top-K** | Cuántos chunks devuelve la búsqueda (top-10 = los 10 más cercanos). |
| **Threshold (umbral, en retrieval)** | Distancia máxima aceptable; por encima, el chunk es demasiado distinto y se descarta. En pgvector el operador `<=>` da distancia coseno entre 0 (idénticos) y 2 (opuestos); umbral típico de OpenAI: **0.5–0.7**. |
| **Recall vs Precision** | **Recall** = traer todo lo potencialmente relevante (con ruido). **Precision** = traer solo lo claramente relevante (puede dejar joyas fuera). No se maximizan a la vez. |
| **Filtros** | Condiciones estructurales (sector, año) que restringen qué chunks son candidatos antes/durante la búsqueda. |
| **Query rewriting** | Pedir al LLM una "consulta técnica concisa". Va bien con entradas cortas mal formuladas; falla con entradas largas multi-tema. |
| **Sub-query decomposition** | El LLM parte la entrada en varias sub-queries; cada una se busca y los resultados se fusionan (RRF). Mejora recall, multiplica coste. |
| **Step-back prompting** | Subir un nivel de abstracción antes de buscar. Brilla en QA sobre conocimiento estructurado; flojo en dominios *narrow* como estimación. |
| **HyDE** (*Hypothetical Document Embeddings*) | Embeber una **respuesta hipotética** generada por el LLM en vez de la pregunta (un documento sintético se parece más a tus documentos). Falla si el modelo alucina. |

### 10.2 Recuperación avanzada *(Sesión 10)*

| Término | Definición |
|---|---|
| **Reranking** | Una segunda etapa que **reordena** los candidatos por relevancia fina (patrón *recall-then-rerank*: red amplia barata → reordenado preciso). |
| **Bi-encoder** | Codifica cada texto **por su cuenta** → un vector. Rápido, precalculable, escala a millones. Bueno encontrando candidatos, **mediocre ordenándolos**. |
| **Cross-encoder** | Mete consulta y documento **juntos** y devuelve una nota de relevancia del par. **Preciso pero no precalculable** (una inferencia por par, en cada consulta). |
| **Golden set** | Colección pequeña de consultas reales, cada una **anotada a mano** con sus documentos relevantes. La "verdad de referencia". |
| **Ground truth** | La respuesta correcta acordada de antemano, contra la que comparas. |
| **precision@k** | `(documentos relevantes entre los k devueltos) / k`. Mide la calidad de los *k* que llegan al LLM. |
| **Mediana** | El valor del medio al ordenar las medidas; más robusta que la media cuando hay pocos datos y algún pico atípico (se usa para medir latencia). |
| **Búsqueda léxica (sparse)** | Busca **términos literales**, pesando los raros (BM25/TF-IDF). Ve identificadores exactos ("Stripe"), no paráfrasis. |
| **Búsqueda semántica (dense)** | Busca por **significado** con embeddings. Ve paráfrasis, pero diluye lo literal. |
| **Búsqueda híbrida** | Ejecutar léxica + semántica **y fusionar** (dejar de elegir). |
| **`tsvector` / `tsquery` / `@@` / `ts_rank`** | Full-text en PostgreSQL: texto preprocesado / consulta preprocesada / operador que comprueba el match / nota de relevancia léxica. |
| **Stemming** | Reducir cada palabra a su raíz ("integraciones/integración/integrar" → una forma); depende del idioma (config `'spanish'`). |
| **RRF** (*Reciprocal Rank Fusion*) | Fusiona varios rankings usando **solo la posición**: `Σ 1/(k+rank)`, con k≈60. Premia el **consenso** (aparecer arriba en varios rankings). |
| **Expansión (multi-query)** | Generar varias **paráfrasis de la misma intención** (combate la lotería de la formulación). Se fusiona con RRF. |
| **Descomposición** | Partir una consulta de **varios temas** en sub-consultas, una por tema (combate el embedding promediado). Se fusiona con cobertura por tema. |
| **Round-robin** | Coger por turnos el mejor de cada ranking (1º de A, 1º de B, 2º de A…) para **garantizar cobertura por tema**. |
| **Multi-índice + routing** | Particionar el corpus en colecciones por familia (presupuestos, transcripciones…) y decidir en cuál(es) buscar. |
| **Router** | El componente que decide en qué colección(es) buscar cada consulta. |
| **Columna discriminadora vs tabla por familia** | Dos formas de particionar en Postgres: una tabla con columna `document_type` (si las familias son variaciones de lo mismo) vs una tabla por tipo (si los esquemas divergen). |
| **Filtro duro** | Condición sobre metadatos que **excluye** documentos antes de que la similitud opine (tecnología, fecha…). |
| **Trampa HNSW + filtro** | HNSW busca los vecinos del **universo completo** y el filtro se aplica **después** → un filtro muy selectivo puede vaciar el resultado en silencio. Solución: *iterative scan* o índice parcial. |
| **Decaimiento temporal** | Penalizar la antigüedad de forma **progresiva** (exponencial) en el orden final, en vez de una ventana dura. |
| **Semivida (half-life)** | Cada cuántos días un documento pierde **la mitad** de su peso. Único parámetro, con lectura directa de negocio. |
| **Ponderación dinámica** | Que la **importancia de cada metadato dependa de la consulta** (multiplicadores definidos en configuración). Peligro: "opacidad artesanal" si se abusa. |

---

## 11. Infraestructura web, API y concurrencia (transversal)
*(Sesión 2, 3, 9)*

| Término | Definición |
|---|---|
| **CRUD** | Las operaciones básicas de datos (Create/Read/Update/Delete), el grueso de una web tradicional. |
| **Síncrono / threads** | Modelo donde cada petición ocupa un hilo completo hasta terminar (Rails+Puma, Django+Gunicorn WSGI). |
| **ASGI** | El estándar Python para servidores web **asíncronos** (sucesor de WSGI). |
| **async/await** | Sintaxis para que el código **suelte el hilo** mientras espera (I/O) y atienda otras tareas entretanto. |
| **I/O-bound** | Trabajo que pasa el tiempo *esperando* (red, disco), no calculando — justo el perfil de llamar a un LLM. |
| **Pydantic `BaseSettings`** | Patrón estándar que carga variables de entorno **y** valida su tipo/formato. |
| **`@lru_cache`** | Decorador que cachea el resultado: la configuración se carga una sola vez y se reutiliza (un singleton sin maquinaria de patrones). |
| **APIRouter** | Mecanismo de FastAPI para agrupar y montar endpoints por separado. |
| **slowapi** | Librería de *rate limiting* que se monta como middleware de FastAPI/Starlette. |
| **Rate limiting** | Limitar cuántas peticiones por minuto acepta el servicio (protege coste y estabilidad). |
| **`Retry-After`** | Header HTTP estándar que indica al cliente cuándo reintentar tras un rechazo. |
| **Idempotency key** | UUID que el cliente envía en cada petición; si la key ya se vio, el servicio devuelve el resultado cacheado **sin volver a llamar al LLM**. |

---

> **Mantenimiento:** este glosario se compila de los `*-theory-*_v2.md` de cada sesión. Si añades un término nuevo en un doc de sesión, añádelo aquí en el grupo que corresponda.
