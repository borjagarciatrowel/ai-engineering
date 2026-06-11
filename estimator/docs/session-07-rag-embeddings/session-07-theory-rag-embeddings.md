# Sesión 7 — Teoría: embeddings, selección de modelos y chunking en RAG

> Documento de teoría que resume los cuatro artículos previos a la sesión 7:
> 1. **Embeddings: del texto a la geometría semántica**
> 2. **Selección de modelos de embeddings: trade-offs en producción**
> 3. **Estrategias profesionales de chunking**
> 4. **Chunking del proyecto: presupuestos JSON y transcripciones**
>
> Es la base teórica de la parte de **recuperación (retrieval)** del sistema RAG.
> La persistencia vectorial y la búsqueda en sí las cubre la [Sesión 8](../session-08-rag-bbdd-vectoriales/session-08-theory-rag-bbdd-vectoriales.md).

---

## 0. La idea en una página (para cualquiera)

Imagina que tienes un archivo con todos los presupuestos que tu empresa ha hecho en los últimos años. Cada presupuesto está desglosado en componentes (un módulo de login, una API de pagos, un panel de administración…), cada uno con sus horas, su tecnología y su descripción.

Llega un cliente nuevo y dice: *"necesito un servicio de autenticación con flujos OAuth para una app móvil del sector financiero"*. Quieres que el sistema, **automáticamente**, encuentre los componentes históricos parecidos para ayudarte a estimar el precio. Y quieres que los encuentre **aunque el cliente no use exactamente las mismas palabras** que están en tus documentos: "authentication service" debería encontrar "OAuth 2.0 backend", "JWT authorization module" o "single sign-on integration", aunque ninguno repita literalmente la palabra "authentication".

Eso es **búsqueda semántica** (búsqueda por significado, no por palabras exactas). Para construirla hacen falta tres piezas, y esta sesión cubre las tres:

| Pieza | Pregunta que responde | Analogía |
|-------|----------------------|----------|
| **Embeddings** (Parte 1) | ¿Cómo convierto texto en algo que una máquina pueda comparar por significado? | Darle a cada texto una **coordenada GPS en un mapa de significados**: lo parecido queda cerca. |
| **Selección de modelo** (Parte 2) | ¿Qué "traductor de texto a coordenadas" uso? | Elegir **qué GPS** comprar: hay caros y precisos, baratos y rápidos, especializados… |
| **Chunking** (Partes 3 y 4) | ¿En qué trozos parto mis documentos antes de darles coordenadas? | Decidir **qué pones en cada foto** antes de archivarla: ni el edificio entero borroso, ni un solo ladrillo sin contexto. |

La conclusión más importante de toda la sesión, repetida en los cuatro artículos: **no hay respuesta universal, hay que medir sobre tus propios datos antes de comprometer arquitectura.** Los rankings y los blogs son un punto de partida, no un oráculo.

---

# PARTE 1 — Embeddings: del texto a la geometría semántica

## 1.1 El problema que resuelven (en humano)

Un ordenador no entiende texto; entiende números. El reto es convertir una frase en números **de tal forma que la cercanía entre esos números signifique cercanía de significado**. Si lo consigues, "buscar lo parecido" se reduce a "buscar los puntos más cercanos en un mapa", que es un problema matemático ya resuelto y rapidísimo.

## 1.2 Qué es un embedding

Un **embedding** es, mecánicamente, una función que toma un texto cualquiera y devuelve un **vector de números reales de dimensión fija**. Ejemplos:

- `text-embedding-3-small` (OpenAI) → **1536** dimensiones
- `text-embedding-3-large` (OpenAI) → **3072** dimensiones
- `all-MiniLM-L6-v2` (Sentence Transformers) → **384** dimensiones

```python
from openai import OpenAI
client = OpenAI()

response = client.embeddings.create(
    model="text-embedding-3-small",
    input="OAuth 2.0 authentication backend with JWT tokens for fintech",
)
embedding = response.data[0].embedding   # lista de 1536 floats
```

Lo importante **no es el número de dimensiones**, sino la propiedad que se cumple sobre esos vectores:

> **Textos semánticamente similares producen vectores cercanos en el espacio R^n.**

Si imprimes el vector entero, no verás nada interpretable: una secuencia de números pequeños alrededor de cero. **Ninguna dimensión individual significa nada legible** para un humano (la dimensión 142 no es "lo fintech que es" ni la 803 "la complejidad"). Las dimensiones salen de un proceso de optimización ciego durante el entrenamiento. Lo único que tiene significado son las **direcciones** y las **distancias relativas** entre vectores. Eso es lo que explotamos.

## 1.3 Cómo aprenden la geometría (aprendizaje contrastivo)

**Para no técnicos:** al modelo se le enseña con un juego de "esto se parece, esto no". Millones de veces. De tanto repetir, acaba colocando las frases parecidas juntas en el mapa, sin que nadie le diga explícitamente dónde va cada una.

En detalle, la técnica se llama **aprendizaje contrastivo (contrastive learning)**. Durante el entrenamiento se muestran millones de **tripletes**:

- un **ancla** (un texto),
- un **positivo** (un texto que debería estar cerca semánticamente),
- uno o varios **negativos** (textos no relacionados).

La función de pérdida **castiga** al modelo cuando el ancla queda más cerca del negativo que del positivo, y lo **premia** en el caso contrario. Tras millones de iteraciones, emerge una representación geométrica donde la cercanía mide algo parecido a la similitud semántica.

**Consecuencia práctica clave:** *qué cuenta como "positivo" depende de para qué se entrenó el modelo.*

- Embeddings de propósito general → positivos = parafraseos, traducciones, oraciones consecutivas, pares pregunta-respuesta.
- Embeddings de código → positivos = fragmentos de código que resuelven problemas similares.
- Embeddings multilingües → positivos = traducciones del mismo texto a varios idiomas.

Por eso, si entrenas un modelo con parafraseos de inglés general y luego le pasas presupuestos técnicos en español con jerga financiera, **no esperes el mismo nivel de discriminación** que en el dominio para el que fue entrenado. Esto se aborda en la Parte 2.

> **Nota epistemológica.** Nadie programó las dimensiones del espacio; emergieron. Hay investigación (interpretabilidad mecanística) que intenta descifrar qué codifica cada dirección, pero en producción tratamos el modelo como una **caja negra cuyas distancias funcionan empíricamente** — lo medimos con benchmarks y con eso basta.
>
> El ejemplo clásico `vector("rey") − vector("hombre") + vector("mujer") ≈ vector("reina")` es real, pero de los embeddings de palabras de hace una década (Word2Vec). Con embeddings modernos **de oraciones** esos juegos aritméticos casi nunca salen tan limpios. Lo que sí sigue siendo cierto: vectores cercanos = textos cercanos. Y eso es lo único que necesitas.

## 1.4 Métricas de similitud

Para hablar de "vectores cercanos" hace falta una **métrica**. Hay tres en todas las APIs de búsqueda vectorial, y son las únicas que necesitas conocer.

### Similitud coseno (cosine similarity)
Mide el **ángulo** entre dos vectores. Devuelve un valor entre −1 y 1 (1 = misma dirección, 0 = perpendiculares, −1 = opuestos). Para texto, la práctica es que los valores caigan entre 0 y 1.

```
cosine(A, B) = (A · B) / (||A|| × ||B||)
```

Su rasgo definitorio: **es insensible a la magnitud**, solo mira la dirección. Esto es deseable en texto, porque no queremos que un documento largo (que puede acabar produciendo un vector con mayor magnitud) parezca menos parecido a una consulta corta por el mero hecho de su tamaño.

### Producto escalar (dot product)
Es el **numerador** del coseno: `dot(A, B) = sum(A[i] × B[i])`. Sin acotar, sensible a dirección **y** magnitud. Computacionalmente más barato (no calcula normas).

> **Detalle importante:** la mayoría de modelos modernos (incluido `text-embedding-3-small`) producen vectores **ya normalizados a longitud 1**. Cuando los vectores están normalizados, **dot product y cosine dan exactamente el mismo resultado**. Por eso muchas bases de datos vectoriales usan dot product internamente: misma calidad, menos operaciones por consulta.

### Distancia euclidiana (euclidean distance)
La distancia recta entre los dos puntos: `euclidean(A, B) = sqrt(sum((A[i] − B[i])²))`. Valor entre 0 (idénticos) e infinito. Para vectores normalizados se relaciona con el coseno por `euclidean(A, B)² = 2 − 2 × cosine(A, B)`, así que **ordena los resultados igual** que el coseno: una búsqueda top-k da los mismos resultados en el mismo orden.

### La regla para elegir métrica
> **Usa la que se usó durante el entrenamiento del modelo. Lo indica la model card.**

No hay misterio ni "mejor métrica universal": es una **propiedad del modelo, no una decisión arquitectónica**. Para `text-embedding-3-small` los vectores vienen normalizados, así que coseno y dot product son intercambiables. Para `all-MiniLM-L6-v2`, la model card recomienda coseno.

> Las tres métricas se implementan en ~30 líneas de Python estándar, sin numpy. Es exactamente el `compare.py` del ejercicio pre-sesión.

## 1.5 Lo que un embedding NO resuelve

La narrativa promocional vende los embeddings como bala de plata. No lo son. Cuatro honestidades:

1. **No entienden números, fechas ni códigos identificadores.** Si la consulta es *"presupuestos de 2024"*, no esperes que el embedding filtre por año. Para eso usas **filtros estructurados sobre el metadata**, no similitud vectorial. Los números aparecen como tokens cualesquiera; el modelo no hace aritmética con ellos.

2. **Son débiles para coincidencias exactas de palabras raras.** Si buscas un nombre propio que aparece tal cual, **BM25** (la métrica clásica de frecuencia de términos, TF-IDF) probablemente lo recupere mejor. Por eso muchas búsquedas serias combinan ambos (**hybrid search**, Sesión 10).

3. **Sufren la maldición de la dimensionalidad.** En espacios de muchas dimensiones, las distancias entre pares aleatorios se concentran en un rango estrecho. Por eso ver similitudes de **0.2–0.5 entre textos no relacionados es completamente normal**: el "cero" de no-relación no aparece en la práctica. **Calibra tus umbrales sobre tu propio dataset**; no asumas que `sim > 0.7` significa "muy similar" en absoluto — solo significa "más similar que los pares no relacionados que medí".

4. **La elección de modelo importa muchísimo más que la de métrica.** Pasar de coseno a dot product con un modelo normalizado no cambia nada. Cambiar de un modelo English-only a uno multilingüe cuando tus datos son medio español medio inglés **sí** cambia los resultados drásticamente. (Sobre esto va la Parte 2.)

> **Validación mínima (SANITY_CHECK).** Antes de optimizar nada, embede unos pocos pares de tu propio dominio y comprueba la **estructura** del resultado: un par claramente relacionado debe dar más similitud que uno no relacionado. No es validación formal de retrieval (eso llega en Sesión 11 con `recall@k` y `NDCG`), pero confirma que el pipeline funciona end-to-end.

---

# PARTE 2 — Selección de modelos de embeddings

> La decisión que de verdad mueve el dial de la calidad: **qué modelo usas para vectorizar tus datos.** No hay respuesta universal. Hay precios de 0 a varios $/millón de tokens, dimensionalidades de 384 a 3072, licencias de MIT a propietario cerrado, y benchmarks que dicen cosas distintas según a quién mires.

## 2.1 El panorama (mayo 2026)

Los seis nombres con los que cualquier *AI engineer* debería estar familiarizado, en dos bloques:

| Modelo | Dims | Idioma | Licencia | Coste | MTEB | Carácter |
|--------|------|--------|----------|-------|------|----------|
| **OpenAI `text-embedding-3-small`** ★ | 1536 (MRL) | Multilingüe decente | Propietaria | $0.02/M | ~62 | Caballo de batalla pragmático **(elección del proyecto)** |
| OpenAI `text-embedding-3-large` | 3072 (MRL) | Multilingüe decente | Propietaria | $0.13/M | ~64.6 | Mejor calidad, 6.5× más caro |
| Cohere `embed-v3` | 1024 | Multilingüe fuerte | Propietaria | $0.10/M | ~65 | Líder cross-lingual (100+), reranking integrado |
| Voyage AI `voyage-3-large` | 1024 | Multilingüe | Propietaria | Premium | ~65+ | Optimizado para retrieval |
| **BAAI `bge-m3`** | 1024 | Multilingüe robusto | MIT | Gratis (compute) | ~63 | Dense + sparse + multi-vector, requiere GPU |
| **`all-MiniLM-L6-v2`** | 384 | Inglés-céntrico | Apache 2.0 | Gratis (compute) | ~56 | Ligero, corre en CPU |

- **MRL** = Matryoshka Representation Learning (ver §2.3): permite truncar el vector a dimensiones menores sin re-entrenar.
- **MTEB** = score promedio en el Massive Text Embedding Benchmark (no como filtro grueso único — ver §2.2).
- Otros nombres relevantes que conviene tener en el radar: Google Gemini Embedding 2, Jina v5, Qwen3-Embedding, Nomic.

> **Advertencia de calibración:** precios, dimensionalidades y scores son válidos en mayo de 2026. Los proveedores comerciales recortan precios cada pocos meses y los modelos open source mejoran cada release. **Verifica antes de comprometer una decisión arquitectónica importante.**

## 2.2 MTEB no es lo que parece

El **MTEB Leaderboard** de Hugging Face es la referencia de facto: tareas estandarizadas (retrieval, classification, clustering, reranking, STS) sobre datasets públicos, con un score agregado por modelo. Vale la pena entender qué dice, pero hay **tres cosas que no te dice** y que conviene tener claras antes de usarlo como criterio único:

1. **Mide rendimiento promedio en datasets públicos generalistas.** Tu dominio no es genérico. Un modelo que saca 65 en MTEB sobre noticias en inglés puede sacar 40 sobre tu corpus de presupuestos técnicos en español con jerga financiera — y a la inversa, un modelo mediocre puede brillar en tu nicho. **Los rankings son punto de partida, no oráculo.**

2. **Se ha vuelto un objetivo de optimización en sí mismo.** Muchos modelos están afinados específicamente para subir su score MTEB, que no es lo mismo que producir mejores resultados en aplicaciones reales. *Cuando una métrica se convierte en target, deja de ser buena métrica* (la misma dinámica que afectó a los SAT scores o a ImageNet).

3. **La variación por chunking puede ser tan grande como la variación entre modelos.** Investigación reciente (Vectara, NAACL 2025) midiendo 25 configuraciones de chunking sobre 48 modelos lo confirma. **Conclusión operativa:** invertir tiempo en optimizar tu chunker rinde más que obsesionarte con qué modelo es 1-2 puntos mejor en MTEB. (Por eso la Parte 3 es el artículo más extenso.)

> **Forma honesta de usar MTEB:** como filtro grueso para descartar modelos claramente débiles, y como referencia secundaria. **Forma correcta de elegir modelo:** hacer benchmark sobre tus propios datos con tus consultas reales.

## 2.3 Matryoshka (MRL): truncar sin perder calidad

**Para no técnicos:** como las muñecas rusas que se anidan unas dentro de otras, el modelo aprende a guardar lo más importante en las **primeras** dimensiones. Así puedes "cortar" el vector y quedarte con la parte de delante sin perder casi calidad.

En detalle, **Matryoshka Representation Learning (MRL)**: durante el entrenamiento el modelo se optimiza simultáneamente para producir embeddings buenos a varias dimensionalidades anidadas (256, 512, 1024, 1536, 3072). Como las primeras dimensiones cargan más información, puedes **truncar el vector a cualquier longitud soportada y conservar la mayor parte de la calidad semántica**. (OpenAI reportó que `text-embedding-3-large` truncado a 256 supera a `ada-002` completo a 1536.)

Dos formas de aplicarlo:

- **Vía parámetro de la API (correcta):** pasas `dimensions=256` en la llamada y el servidor devuelve el embedding ya truncado **y renormalizado**.
- **Vía truncado manual:** si ya tienes el vector completo guardado y quieres una versión más corta sin re-llamar a la API, lo truncas tú (`full[:256]`). **Gotcha:** al truncar pierdes la norma unitaria, y muchas métricas/BBDD asumen vectores normalizados. **Hay que renormalizar a mano.**

> **¿Cuándo merece la pena truncar?** Cuando vas a tener millones de vectores y el coste de storage o la latencia de búsqueda empiezan a importar. Para los ~15 presupuestos del proyecto, la diferencia entre 1536 y 256 se mide en megabytes, no es la prioridad. Pero conviene saber que la palanca existe.

## 2.4 Los cinco ejes de decisión

La elección de modelo se reduce a balancear cinco ejes. No hay respuesta única; hay un trade-off explícito que aceptas en cada uno:

| Eje | El trade-off | Cuándo domina |
|-----|--------------|---------------|
| **1. Dimensionalidad** | Más dims = más capacidad, pero más bytes/vector, más latencia y más tiempo de búsqueda. | Sistemas con cientos de millones de vectores (¿cabe en RAM?). Irrelevante para miles. |
| **2. Idioma del corpus** | Todo inglés → modelos English-centric (rápidos, baratos). Mezcla o idioma no anglosajón → multilingüe obligatorio. | Casi siempre relevante si tus datos no son 100% inglés. |
| **3. Dominio** | Un modelo entrenado en prosa general puede ser mediocre en jerga especializada (médica, legal, código). | Corpus muy especializados (donde probablemente acabes haciendo fine-tuning). |
| **4. Hosting y coste** | API (gestionada, cero infra, coste por token, datos salen) vs self-hosted (cero coste/token, datos no salen, dependes de mantener GPU). | Startup prototipo → API gana. Volumen alto + datos sensibles → self-hosted gana. |
| **5. Licencia** | Propietarios (OpenAI/Cohere/Voyage) no se auto-hostean; MIT/Apache (bge-m3, MiniLM) sí. | Cuando el cliente exige por contrato que **ningún dato salga** de su infra (banca, sanidad, defensa). |

> Estos cinco ejes **no pesan igual en todos los proyectos**. Identifica primero cuál domina en tu contexto y la decisión se simplifica.

## 2.5 La decisión del proyecto: `text-embedding-3-small`

Para el servicio IA del proyecto, el modelo elegido es **`text-embedding-3-small` con dimensiones por defecto (1536)**. Razonado eje por eje:

- **Dimensionalidad:** 1536 es excesivo para el tamaño del corpus, pero el storage extra es despreciable (kilobytes). Mantener el default deja Matryoshka como palanca futura.
- **Idioma:** descripciones en inglés, briefs probablemente en español. No es el mejor multilingüe (lo son `bge-m3` o Cohere), pero es **claramente suficiente**.
- **Dominio:** ningún modelo está especializado en "presupuestos de software", así que cualquier generalista vale; se valida con datos reales en la sesión en vivo.
- **Hosting/coste:** API ya configurada desde la Sesión 01, cero fricción. Ingestar 15 presupuestos (~15.000 tokens) cuesta **$0.0003**. Despreciable.
- **Licencia:** propietaria, pero el proyecto es académico y no hay datos sensibles. Aceptable.

**Por qué no las alternativas:** `text-embedding-3-large` (6.5× más caro por +2 MTEB, no se justifica); `bge-m3` self-hosted (mejor multilingüe pero añade dependencia operativa sin valor pedagógico); `voyage-3-large` (otro proveedor, otra API key, otro billing); `all-MiniLM-L6-v2` local (claramente inferior, se usa solo como **contraste rápido** en vivo).

> La elección no es "el mejor modelo posible", es **"el mejor balance pedagogía/calidad/coste/operación para este contexto"**. Si el contexto cambiara (millones de presupuestos, datos sanitarios, dominio muy específico), la decisión cambiaría. **Mantén esa flexibilidad mental.**

**Sobre medir con código:** el harness del ejercicio compara latencia, dimensionalidad y **norma** de cada modelo. Observaciones cualitativas: OpenAI ~200-400 ms/llamada en serie (red + servidor); MiniLM local ~10-30 ms/texto en CPU. En **batch** las cifras cambian mucho (la API acepta lotes y el throughput sube). Cuando los volúmenes crecen, la **Batch API de OpenAI** da 50% de descuento a cambio de procesamiento asíncrono de hasta 24h. Comprueba siempre que la **norma sea ~1.0**: si no, el modelo no entrega vectores normalizados y tendrás que normalizarlos antes de usar coseno en BBDD que asumen norma 1.

---

# PARTE 3 — Estrategias profesionales de chunking

> **La pregunta con más impacto en la calidad final de tu RAG:** ¿cómo partimos los documentos antes de generar los embeddings?

**Por qué importa (en humano):** si le das el **presupuesto entero** al embedding, el vector resultante es un promedio difuso que mezcla autenticación con inventario con hosting, y no sirve para recuperar nada concreto. Si lo partes en **trozos demasiado pequeños**, pierdes el contexto que hace que cada trozo tenga sentido. El arte está en partir por la **unidad de información correcta**.

## 3.1 Por qué el chunking domina la calidad

Tres datos recientes para fijar el orden de magnitud:

- **Vectara (NAACL 2025):** 25 configuraciones de chunking sobre 48 modelos. *La varianza por cambiar la estrategia de chunking puede ser tan grande como la varianza por cambiar de modelo.*
- **Chroma (2025):** `LLMSemanticChunker` y `ClusterSemanticChunker` alcanzaron recall 0.919 y 0.913; el `RecursiveCharacterTextSplitter` bien tuneado (400 tokens) llegó a 0.88-0.89. Diferencia mejor-peor: **9 puntos de recall**.
- **Vecta (feb 2026, 50 papers):** el recursive splitter de 512 tokens quedó **primero** (69% accuracy); el semantic chunking, supuestamente más sofisticado, **cuarto** (54%). *La sofisticación no garantiza mejor rendimiento; lo garantiza la coincidencia entre la estrategia y el tipo de corpus.*

> **Conclusión operativa (repetida):** mide sobre tus datos antes de comprometer arquitectura. Lo que gana en papers no necesariamente gana en presupuestos de software.

## 3.2 Las cuatro familias mentales

El catálogo de doce estrategias se organiza según **cómo deciden dónde partir el texto**:

| Familia | Cómo decide | Carácter |
|---------|-------------|----------|
| **1. Mecánicas** | Reglas sobre la *forma* del texto (tamaño, separadores, oraciones). No entienden el contenido. | Simples, rápidas, sorprendentemente competitivas. |
| **2. Estructurales** | Explotan el *formato* del documento (Markdown, HTML, JSON, secciones). | La estructura ya codifica la intención del autor. Alto ROI. |
| **3. Semánticas** | Calculan dónde cambia el *significado* (con embeddings o LLM) y parten ahí. | Más costosas; no siempre justifican el coste. |
| **4. Avanzadas / contextuales** | **Complementan** a las anteriores enriqueciendo el chunk con contexto antes de embederlo. | Frontera del estado del arte (2024-2025). |

> **Regla de oro:** empieza con **recursive bien tuneado**. Sube de complejidad solo cuando tengas evidencia medida de que no es suficiente.

## 3.3 Familia 1 — Mecánicas

**Fixed-size.** Parte en bloques de N tokens/caracteres, con `overlap` opcional. No mira el contenido.
```python
def fixed_size_chunks(text, chunk_size, overlap):
    chunks, start = [], 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks
```
- ✅ Corpus muy homogéneo sin estructura interna (logs, streams de eventos, transcripciones planas). Buen *baseline*.
- ❌ Cualquier corpus con estructura (código, documentos formales, conversaciones): romper a mitad de palabra degrada los embeddings de forma medible.
- Overlap típico: **10-20%** del tamaño del chunk.

**Recursive character text splitter.** La **más usada en producción** y la de mejor balance según benchmarks. Define una jerarquía de separadores ordenados por preferencia (`["\n\n", "\n", ". ", " ", ""]`) e intenta partir por el más fuerte que produzca chunks dentro del tamaño objetivo (párrafos → líneas → oraciones → caracteres).
- ✅ Prácticamente cualquier prosa natural. El default razonable a probar primero.
- ❌ Estructura jerárquica formal (JSON, código) donde los separadores genéricos no capturan la jerarquía real.
- Config que rinde bien: **chunk de 400-512 tokens, overlap 10-20%**. Sorprendentemente difícil de batir.

**Sentence-window retrieval.** Indexa **oraciones individuales** (chunks pequeños y precisos para el matching) pero al recuperar devuelve una **ventana ampliada** alrededor de cada oración. El retriever encuentra el "punto exacto" y el generador recibe el "alrededor relevante".
- ✅ Documentos donde la info concreta está en oraciones específicas pero la respuesta necesita contexto vecinal (manuales técnicos, papers, contratos).
- ❌ Documentos donde la info está distribuida en bloques (resúmenes ejecutivos, secciones largas).
- Patrón antiguo que sigue siendo competitivo. LlamaIndex `SentenceWindowNodeParser`.

**Sliding window con overlap variable.** Variante de fixed-size donde el "paso" entre chunks es un parámetro **independiente** del overlap fijo. Controla densidad: pasos pequeños → muchos chunks redundantes; pasos grandes → pocos chunks dispersos (riesgo de perder cosas en las costuras). Útil para texto continuo sin separadores naturales; en la práctica, sentence-window suele ser mejor opción.

## 3.4 Familia 2 — Estructurales

**Document-based (Markdown, HTML, JSON).** La estructura original ya codifica las decisiones del autor sobre dónde empieza y acaba una idea. Markdown → respeta headers; HTML → respeta tags; JSON → respeta la jerarquía de claves.
```python
from langchain_text_splitters import MarkdownHeaderTextSplitter
markdown_splitter = MarkdownHeaderTextSplitter(
    headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3")],
)
```
Para JSON **no hay splitter genérico** que funcione bien, porque la "estructura significativa" depende del dominio (en un presupuesto, un componente es la unidad lógica; en una API spec, un endpoint). El chunker JSON suele ser **custom** — exactamente lo que hacemos en la Parte 4.
- ✅ Documentos con estructura explícita y fiable. **Microsoft Azure (2025) mostró que añadir el header de cada chunk como metadata enriquecido sube la accuracy de QA entre 15 y 25 puntos.** La estructura es una mina de oro.
- ❌ Documentos sin estructura (transcripciones planas, OCR de baja calidad, redes sociales).

**Hierarchical / parent-child chunking.** Indexa chunks **pequeños** (retrieval preciso) pero asocia cada uno a su chunk **padre** (más grande), de modo que al recuperar puedes pasar al LLM el chunk pequeño que coincidió **y también** el contexto del padre.
- ✅ Documentos largos donde una pregunta concreta tiene respuesta en un fragmento puntual pero solo se entiende con contexto amplio (manuales, libros técnicos, documentos legales).
- ❌ Corpus de chunks ya pequeños y autocontenidos (FAQs, tickets breves).
- **Importante:** es una **arquitectura de retrieval**, no solo una estrategia de chunking. Implica decidir qué se indexa (los hijos) y qué se devuelve (los padres o ambos). LangChain `ParentDocumentRetriever`, LlamaIndex `HierarchicalNodeParser`.

## 3.5 Familia 3 — Semánticas

**Semantic chunking.** Calcula embeddings de oraciones consecutivas y corta donde la similitud cae por debajo de un umbral (*donde el significado cambia, corta*).
```python
from langchain_experimental.text_splitter import SemanticChunker
semantic_splitter = SemanticChunker(
    embeddings=OpenAIEmbeddings(model="text-embedding-3-small"),
    breakpoint_threshold_type="percentile",
    breakpoint_threshold_amount=95,
)
```
- ✅ Documentos multi-tema sin estructura explícita (papers con secciones implícitas, posts largos, ensayos).
- ❌ Documentos cortos y enfocados, o texto donde las oraciones consecutivas tienen alta similitud por diseño (jerga repetitiva, plantillas legales).
- **Coste real (que los tutoriales esconden):** requiere embedear **cada oración** durante la ingesta, multiplicando coste y latencia. Para 10.000 documentos × 100 oraciones = un millón de llamadas extra. Y las ganancias sobre recursive bien tuneado son a menudo **marginales**.

**Cluster semantic chunking.** En lugar de cortar secuencialmente, **agrupa oraciones similares aunque no sean consecutivas** (usando HDBSCAN o similar).
- ✅ Discursos largos donde un tema reaparece, transcripciones de mesa redonda, libros con motivos recurrentes.
- ❌ La mayoría de corpus técnicos (ideas organizadas linealmente). **Rompe la trazabilidad:** un chunk clusterizado no tiene "lugar" en el documento original, lo que complica citar la fuente.

**LLM-based / propositional chunking.** La más cara y, en algunos benchmarks, la mejor. Le das el documento a un LLM y le pides que extraiga **proposiciones autocontenidas** (afirmaciones que tienen sentido aisladas).
```
Decompose the following text into the smallest set of self-contained propositions.
Each proposition should: express a single atomic fact; be understandable without
the surrounding text; resolve all pronouns to explicit entities.
```
- ✅ Corpus de alto valor donde la calidad justifica llamar a un LLM por documento (documentación crítica, base de conocimiento, contenido legal).
- ❌ Corpus grandes donde el coste de ingesta se vuelve prohibitivo (un millón de documentos = cientos/miles de dólares solo en chunking).
- En Chroma (2025), `LLMSemanticChunker` alcanzó el máximo del estudio (0.919 recall). Prototípico de *"más caro pero efectivo cuando puedes permitírtelo"*.

## 3.6 Familia 4 — Avanzadas y contextuales

> **No son alternativas a recursive o semantic; son complementos** que mejoran el resultado de cualquier estrategia base.

**Late chunking** (Jina AI, finales 2024). Invierte el orden tradicional: en vez de partir primero y embedear cada chunk aislado, **embede el documento entero primero** (dejando que el modelo vea todo el contexto) y luego extrae los embeddings de cada chunk de la representación global. Requiere modelo con **contexto largo (8K-32K tokens)** y token-level embeddings (`jina-embeddings-v3`, algunos de OpenAI).
- ✅ Documentos donde el significado de cada parte depende fuertemente del contexto global ("el modelo" en un paper de ML).
- ❌ Modelos sin contexto largo (la mayoría de open source ligeros, incluido `all-MiniLM-L6-v2`).
- Emergente. Si tu pipeline ya funciona, probablemente no compense aún; ten el concepto presente.

**Agentic chunking.** Un agente con tool calls **decide dinámicamente** cómo partir cada sección (recursive aquí, structural allí, semantic en otra parte), delegando la decisión humana.
- ✅ Corpus heterogéneo donde no quieres mantener N pipelines (un sistema enterprise que ingesta emails, contratos, papers y código a la vez).
- ❌ Corpus homogéneo, o cualquier sistema con restricciones de coste de ingesta (los agentes son los más caros).

**Query-dependent chunking** (AI21, 2026). En vez de chunking estático en ingesta, **indexa varias resoluciones** del mismo documento (100, 200, 500, 1000 tokens) y en tiempo de consulta elige cuál usar según la pregunta. Preguntas concretas → chunks pequeños; preguntas abiertas → chunks grandes.
- ✅ Corpus donde el mismo documento se consulta de formas muy distintas.
- ❌ La mayoría de casos (patrón de consulta predecible); multiplica el storage por N resoluciones.

**Contextual Retrieval (Anthropic).** **La técnica que probablemente vale la pena implementar de inmediato** si tu pipeline ya funciona pero no termina de afinar. Publicada por Anthropic en septiembre de 2024. Antes de embedear cada chunk, lo **enriquece con un párrafo corto de contexto generado por un LLM** que sitúa ese chunk dentro del documento completo.
```
<document>{whole_document}</document>
Here is the chunk we want to situate within the whole document:
<chunk>{chunk_content}</chunk>
Please give a short succinct context to situate this chunk within the overall
document for the purposes of improving search retrieval. Answer only with the
succinct context and nothing else.
```
El contexto generado se **prepende** al chunk antes de embederlo e indexarlo:
```
[Generated context: This chunk discusses Q3 2024 revenue figures for the European
market, mentioned in section 4.2 of the annual report.]
[Original chunk: Revenue grew by 3% over the previous quarter...]
```
- **Números de Anthropic:** 35% de reducción de fallos de retrieval solo con contextual embeddings; 49% combinándolo con BM25 contextual; **hasta 67%** sumando reranking. Los benchmarks independientes confirman la dirección.
- ✅ Prácticamente cualquier corpus con documentos largos donde los chunks pierden contexto al aislarse (casi todos los casos reales).
- ❌ Chunks pequeños autocontenidos (FAQs) y sistemas con coste de ingesta como restricción dura.
- **Coste:** una llamada a LLM por chunk en ingesta. Anthropic recomienda **prompt caching** para no reenviar el documento completo cada vez, lo que baja el coste a ~$1 por millón de tokens contextualizados.

## 3.7 Cómo elegir: criterios honestos

1. **Empieza con `RecursiveCharacterTextSplitter`** (400-512 tokens, 10-20% overlap). Repetidamente entre las mejores opciones, la más barata de operar. Cambia solo con evidencia medida.
2. **Si hay estructura explícita (Markdown, HTML, JSON), úsala.** Document-based + metadata enriquecido es la palanca de mayor ROI conocida (Microsoft Azure: +15-25 puntos).
3. **Si los chunks pierden sentido al aislarse, considera Contextual Retrieval.** La más madura de las "avanzadas".
4. **Semantic / LLM-based son legítimas pero caras.** Justifícalas con datos sobre tu corpus, no porque un blog las elogie.
5. **Parent-child es arquitectura, no solo chunking.** No la introduzcas si tu pipeline aún no funciona con una estrategia plana.
6. **Late / agentic / query-dependent son emergentes.** Mantente al tanto; no las metas en producción sin un caso que las justifique. *La novedad no es por sí misma una ventaja.*
7. **Y lo más importante: el mejor chunking depende del tipo de documento.** Un corpus heterogéneo casi siempre se beneficia de **distintas estrategias para distintos tipos** dentro del mismo pipeline. Es exactamente la situación del proyecto (Parte 4).

---

# PARTE 4 — Chunking del proyecto: presupuestos JSON y transcripciones

> Aterriza el catálogo de la Parte 3 a los **dos tipos de documento reales** del proyecto, con propiedades estructurales radicalmente distintas.

| Tipo de documento | Estructura | Unidad lógica | Estrategia correcta |
|-------------------|-----------|---------------|---------------------|
| **Presupuestos históricos (JSON)** | Jerárquica explícita, esquema predecible | El **componente** del presupuesto | Estructural (respeta la jerarquía JSON) |
| **Transcripciones de reuniones** | Texto plano de ~45 min, sin estructura | El **bloque temático** | Semántica (topic-based segmentation) |

## 4.1 Dos tipos de documento, dos chunkers

El servicio IA tiene **dos chunkers especializados que comparten una interfaz común**, no un chunker genérico con condicionales internos. *Si dos entradas requieren tratamiento radicalmente distinto, es más limpio dos implementaciones explícitas.*

```python
from abc import ABC, abstractmethod

class Chunker(ABC):
    """Common interface for any chunking strategy in the pipeline."""
    @abstractmethod
    def chunk(self, document: dict | str) -> list[Chunk]: ...

class JSONStructuralChunker(Chunker):     # presupuestos → 1 componente = 1 chunk
    ...
class TopicSegmentationChunker(Chunker):  # transcripciones → bloques temáticos
    ...
```
La interfaz común sirve para dos cosas: hacer cada chunker **testeable por separado** y dejar la puerta abierta a meter más estrategias en vivo. Ambos chunkers son responsabilidad del **servicio IA (Python + FastAPI)**; el backend de negocio (Rails de referencia) solo invoca el endpoint de ingesta.

## 4.2 El chunker JSON estructural

**Por qué los splitters genéricos fallan** con un presupuesto JSON:
1. El splitter trata llaves, comillas y comas como caracteres normales → corta a mitad de una clave (`"client_metadata": {"sector":` en un chunk, `"finance", "country":` en el siguiente). El embedding que sale es **ruido**.
2. Aunque el corte caiga bien, **se pierde la jerarquía padre-hijo**: un chunk con `"OAuth 2.0 authentication backend"` sin saber de qué cliente/sector/año es, competirá con cientos de componentes de auth de sectores irrelevantes.
3. Si serializas el JSON a texto plano antes de chunkear, pierdes la jerarquía explícita que el formato capturaba.

**Tres decisiones de diseño del `JSONStructuralChunker`:**

- **Decisión 1 — Granularidad: un componente = un chunk.** No el presupuesto entero (pierde especificidad) ni cada campo suelto (pierde coherencia). El componente coincide con la **unidad de razonamiento del dominio**: cuando un cliente pide un OAuth backend, eso es lo que queremos recuperar.

- **Decisión 2 — Contenido del chunk: texto legible enriquecido con contexto del padre.** El campo `text` (lo que se embede) **no es el JSON crudo**, sino una representación textual que combina el componente con el contexto del presupuesto padre:
  ```
  [Project: Mobile banking API with OAuth 2.0 authentication and PSD2...]
  [Client sector: finance | Year: 2024 | Main tech: ruby_on_rails]

  Component: OAuth 2.0 authentication backend
  Description: Implementation of OAuth 2.0 flows with JWT-based session...
  Tech stack: ruby_on_rails, postgresql, redis
  Complexity: high
  Estimated hours: 120
  ```
  Las dos primeras líneas entre corchetes son **contextual chunk headers** (info del padre prepended al chunk). Es la **versión estática y barata** de Contextual Retrieval (§3.6): usa el contexto que ya está en el JSON **sin llamar a un LLM**. Es la palanca de mayor ROI conocida en RAG.

- **Decisión 3 — Metadata: campos filtrables que NO se embeden.** El sector, el año, la tecnología, la complejidad y las horas van en `metadata`. Sirve para **filtrar resultados** (`sector = 'finance' AND year >= 2023`) y **devolver info estructurada** al cliente sin parsear el texto.

```python
@dataclass
class Chunk:
    chunk_id: str
    text: str
    metadata: dict[str, Any]
    token_count: int   # vía tiktoken
```
> **Lo que queda como trabajo del ejercicio (production-ready):** validación Pydantic del schema de entrada (un campo faltante no debería tirar `KeyError` opaco), logging estructurado de chunks por presupuesto, manejo del caso límite "componente con descripción anormalmente larga", e integración con `POST /embeddings/ingest`. El esqueleto es el chasis; esas decisiones las tomas tú.

## 4.3 El segmentador por temas (transcripciones)

**Por qué los splitters de carácter destrozan una transcripción:** una transcripción típica tiene 6.000-12.000 tokens, **cero estructura formal**, hablantes alternados (`Speaker A:`), temas que se interrumpen y vuelven 10 minutos después, y mucho contenido de baja densidad (confirmaciones, divagaciones). Un `RecursiveCharacterTextSplitter` corta en posiciones arbitrarias, a veces a mitad de una intervención, dejando ideas partidas entre dos chunks.

La estrategia correcta es **topic-based segmentation** (familia semántica): embede oraciones/intervenciones consecutivas, detecta dónde la similitud entre vecinos cae por debajo de un umbral, y parte ahí. El resultado son chunks que coinciden con **bloques temáticos coherentes**.

**Tres decisiones del `TopicSegmentationChunker`** (paralelas a las del JSON, razonamiento distinto):

- **Decisión 1 — Granularidad: cada bloque temático = un chunk.** No por oración (demasiado pequeño) ni por minuto (no respeta el contenido). Se segmenta **donde el tema cambia**; la duración varía (a veces 30 s, a veces 8 min). La granularidad se ajusta al contenido, no al reloj.
- **Decisión 2 — Contenido: el bloque temático con su contexto de reunión** (metadata de la reunión prepended: cliente, fecha, participantes, fase).
  ```
  [Meeting: Requirements gathering · 2024-03-15]
  [Client: FintechCorp · Phase: discovery]
  [Speakers: Antonio (consultant), Maria (CTO), Pedro (lead dev)]

  Topic block: Authentication and security
  Maria: We need OAuth 2.0 with refresh tokens, and we need it to work with our SAML provider...
  ```
- **Decisión 3 — Metadata: información temporal y de hablante** (posición early/mid/late, timestamp si lo hay, hablante dominante, tema detectado). Filtros típicos: por fecha, cliente, fase.

```python
def _detect_topic_boundaries(self, utterances) -> list[int]:
    embeddings = self._model.encode([u.text for u in utterances], normalize_embeddings=True)
    boundaries = [0]
    for i in range(1, len(embeddings)):
        similarity = float(embeddings[i] @ embeddings[i - 1])
        if similarity < self._threshold:   # default 0.55
            boundaries.append(i)
    return boundaries
```
> **Dos sutilezas importantes:**
> - El `similarity_threshold = 0.55` es un **punto de partida, no universal**. Demasiado alto → demasiados bloques; demasiado bajo → bloques enormes. Depende del modelo y del estilo de transcripción; se calibra en vivo.
> - Para la segmentación interna se usa **`all-MiniLM-L6-v2` local**, aunque el resto del sistema use `text-embedding-3-small`. Razón: hay que embedear muchas oraciones rápido y barato; un modelo local de 384 dims es perfecto para esto, mientras que llamar a la API por cada oración sería innecesariamente caro y lento. **Diferentes piezas del pipeline pueden usar diferentes modelos de forma legítima.**

## 4.4 Metadata enrichment: la palanca subestimada

El hallazgo de Microsoft Azure (enriquecer cada chunk con metadata estructural **sube la accuracy de QA 15-25 puntos** sin tocar nada más) es de los de mejor relación esfuerzo/impacto. Ambos chunkers ya lo hacen de **tres formas**:

1. **Headers contextuales DENTRO del texto** que se embede (el bloque entre corchetes). El vector incorpora esa info en su geometría semántica.
2. **Metadata estructurada FUERA del texto**, en el dict `metadata`. No se embede pero viaja con el chunk a la BBDD vectorial. La [Sesión 8](../session-08-rag-bbdd-vectoriales/session-08-theory-rag-bbdd-vectoriales.md) muestra que **pgvector permite filtrar por esta metadata combinando búsqueda vectorial con filtros SQL clásicos**: *"componentes de auth para fintech del último año"* = búsqueda vectorial por la parte semántica + `client_sector = 'finance' AND year >= 2024`.
3. **IDs trazables** (`{budget_id}::{component_id}`, `{meeting_id}::{block_index}`). Operacionalmente crítico: permite citar la fuente al usuario, auditar resultados, o invalidar chunks cuando el documento padre se actualice.

> **Regla práctica — ¿texto o metadata?** Si la información **cambia el significado semántico** para una consulta natural (el sector importa para distinguir "auth para fintech" de "auth para e-commerce"), va en el **texto**. Si es **discreta y se usa para filtrar** (`year`, `complexity`, `estimated_hours`), va en **metadata**. A veces va en ambos (el sector pesa semánticamente **y** filtra): no es redundancia injustificada, cada copia cumple un rol distinto.

## 4.5 Composición en el servicio IA (IngestRouter)

¿Cómo decide el servicio qué chunker aplicar? Para esta sesión, simple: `POST /embeddings/ingest` recibe un campo `document_type` en el body y enruta internamente.

```python
class IngestRouter:
    """Routes documents to the appropriate chunker based on type."""
    def __init__(self, json_chunker, transcript_chunker):
        self._chunkers = {"budget": json_chunker, "transcript": transcript_chunker}

    def chunk(self, document: dict, document_type: str) -> list[Chunk]:
        if document_type not in self._chunkers:
            raise ValueError(f"Unknown document type: {document_type}")
        return self._chunkers[document_type].chunk(document)
```

**Flujo completo:** Backend de negocio `POST /embeddings/ingest` (con `document_type`) → `IngestRouter` → `JSONStructuralChunker` **o** `TopicSegmentationChunker` → ambos convergen en un **`OpenAIEmbedder` compartido** (`text-embedding-3-small`, batch, 1536 dims) → `IngestResponse` (chunks + embeddings + metadata) → **BBDD vectorial (PostgreSQL + pgvector)**, que es la Sesión 8.

> **Decisión arquitectónica explícita:** se podría **detectar el tipo automáticamente** (mirar si es JSON o texto plano, inspeccionar la URL del fichero), pero "explícito por payload" es más simple y auditable. La detección automática es **agentic chunking** (§3.6): legítima, pero con coste extra que aquí no se justifica.
>
> Que el backend de negocio sea Rails es **accidental** a la arquitectura: el contrato entre las dos capas es REST simple, independiente del stack. Cualquier cliente HTTP cumple la misma función.

---

# Glosario rápido

| Término | En una frase |
|---------|--------------|
| **Embedding** | Vector de números reales de dimensión fija que representa un texto; textos parecidos → vectores cercanos. |
| **Aprendizaje contrastivo** | Técnica de entrenamiento con tripletes (ancla/positivo/negativo) que induce la geometría semántica. |
| **Similitud coseno** | Mide el ángulo entre vectores, ignora la magnitud. La métrica más común para texto. |
| **Producto escalar (dot product)** | Numerador del coseno; idéntico al coseno si los vectores están normalizados, más barato de calcular. |
| **Normalización** | Llevar un vector a longitud 1. Muchas BBDD lo asumen; comprueba que la norma sea ~1.0. |
| **MTEB** | Massive Text Embedding Benchmark. Referencia de facto, pero no oráculo: mide promedios generalistas. |
| **Matryoshka (MRL)** | Entrenamiento que permite truncar el vector a menos dimensiones conservando casi toda la calidad. |
| **Chunking** | Partir documentos en trozos antes de embederlos. La decisión de mayor impacto en la calidad del retrieval. |
| **Overlap** | Solapamiento entre chunks consecutivos (típico 10-20%) para no perder ideas en las fronteras. |
| **Contextual chunk header** | Info del documento padre prepended al texto del chunk antes de embederlo (palanca de alto ROI). |
| **Contextual Retrieval** | Técnica de Anthropic: enriquecer cada chunk con contexto generado por LLM antes de embederlo. |
| **BM25** | Métrica clásica de búsqueda por términos exactos (TF-IDF). Complementa a los embeddings (hybrid search). |
| **Maldición de la dimensionalidad** | En muchas dimensiones las distancias se concentran; por eso `sim` 0.2-0.5 entre no-relacionados es normal. |

---

# Cómo aterriza en nuestro proyecto

Esta teoría es la base de la parte de **ingesta y recuperación** del estimador:

- **Modelo:** `text-embedding-3-small` (1536 dims, normalizado → coseno/dot intercambiables).
- **Dos chunkers** con interfaz común: `JSONStructuralChunker` (presupuestos, 1 componente = 1 chunk con contexto del padre) y `TopicSegmentationChunker` (transcripciones, bloques temáticos con `all-MiniLM-L6-v2` local).
- **Metadata enrichment** en texto (headers contextuales) **y** fuera (campos filtrables + IDs trazables).
- **`IngestRouter`** que enruta por `document_type` hacia un `OpenAIEmbedder` compartido.
- La persistencia de los vectores resultantes y la búsqueda semántica con filtros SQL las cubre la **[Sesión 8 — pgvector](../session-08-rag-bbdd-vectoriales/session-08-theory-rag-bbdd-vectoriales.md)**.

> **El hilo conductor de la sesión:** no hay configuración universal. El modelo, la métrica y sobre todo la estrategia de chunking se eligen **midiendo sobre tus propios datos** — los benchmarks y los blogs son el mapa, no el territorio.
