# Sesión 07 — Embeddings, selección de modelos y chunking (versión clara)

> Versión simplificada del resumen de los 4 artículos de la Sesión 7. Misma información, menos paja. Cada término técnico se explica en una frase.
> **Hilo conductor:** un sistema que busca componentes de presupuestos antiguos parecidos para estimar un proyecto nuevo, **por significado y no por palabras exactas**.

---

## Glosario base (léelo una vez y vuelve cuando haga falta)

| Término | Qué es, en una frase |
|---|---|
| **Embedding** | Convertir un texto en una lista de números (un "vector") que captura su significado. Textos parecidos → vectores cercanos. |
| **Vector / espacio R^n** | El embedding es un punto en un espacio de muchas dimensiones (n). "Cercanía" ahí ≈ parecido de significado. |
| **Dimensiones** | Cuántos números tiene el vector (p.ej. 384, 1536, 3072). Más dims = más capacidad, pero más bytes y latencia. |
| **Búsqueda semántica** | Buscar por significado (vectores cercanos), no por coincidencia literal de palabras. |
| **Similitud / distancia** | Cómo se mide cuán cerca están dos vectores. Más cerca = más parecidos. |
| **Chunking** | Partir un documento en trozos ("chunks") antes de convertirlos en embeddings. La decisión de mayor impacto en la calidad. |
| **Chunk** | Cada trozo en que se parte un documento. La unidad que se indexa y se recupera. |
| **Metadata** | Datos *sobre* el chunk que no van en su texto: sector, año, tecnología, complejidad. Sirven para filtrar. |
| **Model card** | La ficha oficial de un modelo: cómo se entrenó, qué métrica usar, sus límites. |

---

## La idea en una página

Tienes un archivo con los presupuestos de tu empresa, desglosados en componentes (login, API de pagos, panel de admin…), cada uno con sus horas, tecnología y descripción. Llega un cliente: *"necesito un servicio de autenticación con flujos OAuth para una app móvil financiera"*. Quieres que el sistema encuentre **automáticamente** los componentes históricos parecidos — **aunque el cliente no use las mismas palabras** ("authentication service" debería encontrar "OAuth 2.0 backend", "JWT module" o "single sign-on").

Eso es **búsqueda semántica**. Necesita tres piezas, y esta sesión cubre las tres:

| Pieza | Pregunta que responde | Analogía |
|---|---|---|
| **Embeddings** (Parte 1) | ¿Cómo convierto texto en algo que la máquina compare por significado? | Darle a cada texto una **coordenada GPS** en un mapa de significados. |
| **Selección de modelo** (Parte 2) | ¿Qué "traductor de texto a coordenadas" uso? | Elegir **qué GPS** comprar: caros y precisos, baratos y rápidos, especializados… |
| **Chunking** (Partes 3-4) | ¿En qué trozos parto mis documentos antes de darles coordenadas? | Qué pones en cada foto antes de archivarla: ni el edificio entero borroso, ni un ladrillo sin contexto. |

> **La conclusión que repiten los 4 artículos:** no hay respuesta universal. **Hay que medir sobre tus propios datos antes de comprometer arquitectura.** Los rankings y los blogs son el mapa, no el territorio.

> Persistencia vectorial y búsqueda → [Sesión 8 — pgvector](../session-08-datadrivenai-bbdd-vectoriales/session-08-theory-datadrivenai-bbdd-vectoriales.md).

---

# Parte 1 — Embeddings: del texto a la geometría semántica

## El problema que resuelven

Un ordenador entiende números, no texto. El reto: convertir una frase en números **de forma que la cercanía entre ellos signifique cercanía de significado**. Si lo consigues, "buscar lo parecido" se reduce a "buscar los puntos más cercanos en un mapa" — un problema matemático ya resuelto y rapidísimo.

## Qué es un embedding

> **Embedding** = función que toma un texto y devuelve un **vector de números reales de dimensión fija**.

Ejemplos: `text-embedding-3-small` (OpenAI) → **1536** dims · `text-embedding-3-large` (OpenAI) → **3072** · `all-MiniLM-L6-v2` (Sentence Transformers) → **384**.

```python
from openai import OpenAI
client = OpenAI()
response = client.embeddings.create(
    model="text-embedding-3-small",
    input="OAuth 2.0 authentication backend with JWT tokens for fintech",
)
embedding = response.data[0].embedding   # lista de 1536 floats
```

Lo importante **no es el número de dimensiones**, sino la propiedad que cumplen esos vectores:

> **Textos semánticamente similares producen vectores cercanos en el espacio R^n.**

Si imprimes el vector no verás nada legible: números pequeños alrededor de cero. **Ninguna dimensión individual significa nada interpretable** (la 142 no es "lo fintech que es"); emergen de una optimización ciega en el entrenamiento. Lo único con significado son las **direcciones** y **distancias relativas** entre vectores.

## Cómo aprenden la geometría (aprendizaje contrastivo)

> **Aprendizaje contrastivo (contrastive learning)** = entrenar con un juego de "esto se parece, esto no" millones de veces, hasta que el modelo coloca las frases parecidas juntas sin que nadie le diga dónde va cada una.

En detalle, se le muestran millones de **tripletes**: un **ancla** (un texto), un **positivo** (debería estar cerca) y uno o varios **negativos** (no relacionados). La pérdida **castiga** que el ancla quede más cerca del negativo que del positivo, y lo **premia** al revés.

> **Consecuencia clave:** *qué cuenta como "positivo" depende de para qué se entrenó el modelo.* General → parafraseos, traducciones, pares Q-A. De código → fragmentos que resuelven problemas similares. Multilingüe → traducciones del mismo texto.

Por eso, si entrenas con inglés general y le pasas presupuestos en español con jerga financiera, **no esperes el mismo nivel de discriminación** que en su dominio (Parte 2).

> **Nota.** Nadie programó las dimensiones; emergieron. En producción tratamos el modelo como **caja negra cuyas distancias funcionan empíricamente**. El clásico `rey − hombre + mujer ≈ reina` es real pero de los embeddings de *palabras* de hace una década (Word2Vec); con embeddings modernos de *oraciones* casi nunca sale tan limpio. Lo que sí sigue siendo cierto: vectores cercanos = textos cercanos.

## Métricas de similitud

Hay tres en todas las APIs vectoriales, y son las únicas que necesitas:

> **Similitud coseno (cosine)** = mide el **ángulo** entre dos vectores. Entre −1 y 1 (1 = misma dirección, 0 = perpendiculares). **Insensible a la magnitud**, solo mira dirección — deseable en texto, para que un documento largo (vector de más magnitud) no parezca menos parecido a una consulta corta solo por su tamaño. `cosine(A,B) = (A·B) / (||A||×||B||)`.

> **Producto escalar (dot product)** = el **numerador** del coseno: `sum(A[i]×B[i])`. Sin acotar, sensible a dirección **y** magnitud. Más barato (no calcula normas).

> **Detalle importante:** la mayoría de modelos modernos (incluido `text-embedding-3-small`) producen vectores **ya normalizados a longitud 1**. Con vectores normalizados, **dot y cosine dan el mismo resultado** — por eso muchas BBDD usan dot product: misma calidad, menos operaciones.

> **Distancia euclidiana** = distancia recta: `sqrt(sum((A[i]−B[i])²))`, entre 0 (idénticos) e ∞. Para vectores normalizados, `euclidean² = 2 − 2·cosine`, así que **ordena igual** que el coseno (mismos top-k, mismo orden).

> **La regla para elegir métrica: usa la que se usó al entrenar el modelo. Lo indica la model card.** No hay "mejor métrica universal": es propiedad del modelo, no decisión arquitectónica. `text-embedding-3-small` → normalizado (coseno/dot intercambiables); `all-MiniLM-L6-v2` → coseno. Las tres se implementan en ~30 líneas de Python sin numpy (el `compare.py` del ejercicio pre-sesión).

## Lo que un embedding NO resuelve

Cuatro honestidades (no son bala de plata):

1. **No entienden números, fechas ni códigos.** Para *"presupuestos de 2024"* usa **filtros estructurados sobre metadata**, no similitud. Los números son tokens cualesquiera; no hay aritmética.
2. **Débiles para coincidencias exactas de palabras raras.** Un nombre propio literal lo recupera mejor **BM25**, por eso muchas búsquedas combinan ambos (**hybrid search**, Sesión 10).
   > **BM25** = métrica clásica de búsqueda por **términos exactos** (familia TF-IDF: pesa más las palabras poco frecuentes).
3. **Sufren la maldición de la dimensionalidad.**
   > **Maldición de la dimensionalidad** = en muchas dimensiones, las distancias entre pares aleatorios se concentran en un rango estrecho.

   Por eso ver `sim` de **0.2–0.5 entre textos no relacionados es normal**: el "cero" de no-relación no aparece. **Calibra umbrales sobre tu dataset**; `sim > 0.7` solo significa "más similar que los pares no relacionados que medí", no "muy similar".
4. **La elección de modelo importa muchísimo más que la de métrica.** Coseno→dot con modelo normalizado no cambia nada; English-only→multilingüe con datos medio español medio inglés **sí**, drásticamente (Parte 2).

> **Validación mínima (SANITY_CHECK).** Antes de optimizar, embede unos pares de tu dominio y comprueba la **estructura**: un par relacionado debe dar más similitud que uno no relacionado. No es validación formal (eso llega con `recall@k`/`NDCG`), pero confirma que el pipeline funciona end-to-end.

---

# Parte 2 — Selección de modelos de embeddings

> La decisión que de verdad mueve la calidad: **qué modelo usas para vectorizar.** No hay respuesta universal: precios de 0 a varios $/M tokens, dims de 384 a 3072, licencias de MIT a propietario cerrado, benchmarks que discrepan.

## El panorama (mayo 2026)

| Modelo | Dims | Idioma | Licencia | Coste | MTEB | Carácter |
|---|---|---|---|---|---|---|
| **OpenAI `text-embedding-3-small`** ★ | 1536 (MRL) | Multilingüe decente | Propietaria | $0.02/M | ~62 | Caballo de batalla **(elección del proyecto)** |
| OpenAI `text-embedding-3-large` | 3072 (MRL) | Multilingüe decente | Propietaria | $0.13/M | ~64.6 | Mejor calidad, 6.5× más caro |
| Cohere `embed-v3` | 1024 | Multilingüe fuerte | Propietaria | $0.10/M | ~65 | Líder cross-lingual (100+), reranking integrado |
| Voyage AI `voyage-3-large` | 1024 | Multilingüe | Propietaria | Premium | ~65+ | Optimizado para retrieval |
| **BAAI `bge-m3`** | 1024 | Multilingüe robusto | MIT | Gratis (compute) | ~63 | Dense+sparse+multi-vector, requiere GPU |
| **`all-MiniLM-L6-v2`** | 384 | Inglés-céntrico | Apache 2.0 | Gratis (compute) | ~56 | Ligero, corre en CPU |

> **MRL** = Matryoshka Representation Learning (ver abajo): permite truncar el vector a menos dims sin re-entrenar.
> **MTEB** = Massive Text Embedding Benchmark: score promedio en tareas estandarizadas (no es filtro grueso único — ver abajo).

Otros en el radar: Google Gemini Embedding 2, Jina v5, Qwen3-Embedding, Nomic.

> **Advertencia de calibración:** precios, dims y scores son de mayo 2026. Los comerciales recortan precios cada pocos meses y el open source mejora cada release. **Verifica antes de comprometer arquitectura.**

## MTEB no es lo que parece

El **MTEB Leaderboard** (Hugging Face) es la referencia de facto, pero hay **tres cosas que no te dice**:

1. **Mide promedio en datasets públicos generalistas.** Un modelo que saca 65 sobre noticias en inglés puede sacar 40 sobre tu corpus de presupuestos en español — y a la inversa. **Punto de partida, no oráculo.**
2. **Se ha vuelto un objetivo de optimización.** Muchos modelos se afinan para subir su MTEB, que no es producir mejores resultados reales. *Cuando una métrica se vuelve target, deja de ser buena métrica.*
3. **La variación por chunking puede ser tan grande como la variación entre modelos** (Vectara, NAACL 2025). **Conclusión:** optimizar tu chunker rinde más que obsesionarte con 1-2 puntos de MTEB. (Por eso la Parte 3 es la más extensa.)

> **Forma honesta:** MTEB como filtro grueso para descartar modelos débiles. **Forma correcta de elegir:** benchmark sobre tus datos con tus consultas reales.

## Matryoshka (MRL): truncar sin perder calidad

> **MRL** = como las muñecas rusas, el modelo aprende a guardar lo más importante en las **primeras** dimensiones. Así puedes "cortar" el vector y quedarte con la parte de delante sin perder casi calidad.

Se optimiza simultáneamente para varias dims anidadas (256, 512, 1024, 1536, 3072). (OpenAI: `text-embedding-3-large` truncado a 256 supera a `ada-002` completo a 1536.) Dos formas:

| Forma | Cómo | Gotcha |
|---|---|---|
| **Vía parámetro API (correcta)** | `dimensions=256` → el servidor devuelve el vector truncado **y renormalizado** | ninguno |
| **Truncado manual** | si ya tienes el vector completo (`full[:256]`) | al truncar **pierdes la norma unitaria** → **renormaliza a mano** (las BBDD asumen norma 1) |

> **¿Cuándo merece la pena?** Con millones de vectores, cuando storage o latencia importen. Para los ~15 presupuestos del proyecto, son megabytes — no es prioridad, pero la palanca existe.

## Los cinco ejes de decisión

| Eje | El trade-off | Cuándo domina |
|---|---|---|
| **1. Dimensionalidad** | Más dims = más capacidad, pero más bytes/vector y latencia. | Cientos de millones de vectores (¿cabe en RAM?). Irrelevante para miles. |
| **2. Idioma** | Todo inglés → English-centric (rápidos, baratos). Mezcla → multilingüe obligatorio. | Casi siempre, si no es 100% inglés. |
| **3. Dominio** | Modelo de prosa general puede ser mediocre en jerga especializada (médica, legal, código). | Corpus muy especializados (probable fine-tuning). |
| **4. Hosting/coste** | API (gestionada, coste/token, datos salen) vs self-hosted (cero coste/token, datos no salen, mantienes GPU). | Prototipo → API. Volumen alto + datos sensibles → self-hosted. |
| **5. Licencia** | Propietarios (OpenAI/Cohere/Voyage) no se auto-hostean; MIT/Apache (bge-m3, MiniLM) sí. | Cuando el cliente exige que **ningún dato salga** (banca, sanidad, defensa). |

> No pesan igual en todos los proyectos. Identifica cuál domina en tu contexto y la decisión se simplifica.

## La decisión del proyecto: `text-embedding-3-small`

Modelo elegido: **`text-embedding-3-small`, dimensiones por defecto (1536)**. Razonado eje por eje:

- **Dimensionalidad:** 1536 es excesivo, pero el storage extra es despreciable (KB). Default deja Matryoshka como palanca futura.
- **Idioma:** descripciones en inglés, briefs probablemente en español. No es el mejor multilingüe, pero **claramente suficiente**.
- **Dominio:** ningún modelo está especializado en "presupuestos de software"; cualquier generalista vale. Se valida en vivo.
- **Hosting/coste:** API ya configurada (Sesión 01). Ingestar 15 presupuestos (~15.000 tokens) = **$0.0003**. Despreciable.
- **Licencia:** propietaria, pero proyecto académico sin datos sensibles. Aceptable.

**Por qué no las alternativas:** `text-embedding-3-large` (6.5× más caro por +2 MTEB) · `bge-m3` self-hosted (mejor multilingüe pero dependencia operativa sin valor pedagógico) · `voyage-3-large` (otro proveedor/key/billing) · `all-MiniLM-L6-v2` local (inferior; solo como **contraste rápido** en vivo).

> La elección no es "el mejor modelo posible", es **"el mejor balance pedagogía/calidad/coste/operación para este contexto"**. Si el contexto cambiara (millones de presupuestos, datos sanitarios), la decisión cambiaría. **Mantén esa flexibilidad mental.**

**Medir con código:** el harness compara latencia, dims y **norma**. Cifras: OpenAI ~200-400 ms/llamada en serie; MiniLM local ~10-30 ms/texto en CPU. En **batch** el throughput sube mucho. Para volúmenes grandes, la **Batch API de OpenAI** da 50% de descuento (asíncrono hasta 24h). Comprueba siempre que la **norma sea ~1.0**: si no, normaliza antes de usar coseno en BBDD que asumen norma 1.

---

# Parte 3 — Estrategias profesionales de chunking

> **La pregunta con más impacto en la calidad final del RAG:** ¿cómo partimos los documentos antes de generar los embeddings?

**Por qué importa:** el **presupuesto entero** da un vector promedio difuso (mezcla auth + inventario + hosting) que no recupera nada concreto; **trozos demasiado pequeños** pierden el contexto que les da sentido. El arte está en partir por la **unidad de información correcta**.

## Por qué el chunking domina la calidad

| Estudio | Hallazgo |
|---|---|
| **Vectara (NAACL 2025)** | 25 configs × 48 modelos: la varianza por chunking puede ser tan grande como la varianza por modelo. |
| **Chroma (2025)** | `LLMSemanticChunker`/`ClusterSemanticChunker` → recall **0.919**/**0.913**; `RecursiveCharacterTextSplitter` bien tuneado (400 tokens) → **0.88-0.89**. Diferencia: **9 puntos de recall**. |
| **Vecta (feb 2026, 50 papers)** | recursive 512 tokens → **1.º (69%)**; semantic chunking → **4.º (54%)**. *La sofisticación no garantiza mejor rendimiento.* |

> **Conclusión (repetida):** mide sobre tus datos antes de comprometer arquitectura. Lo que gana en papers no necesariamente gana en presupuestos.

## Las cuatro familias mentales

| Familia | Cómo decide dónde partir | Carácter |
|---|---|---|
| **1. Mecánicas** | Reglas sobre la *forma* (tamaño, separadores, oraciones). No entienden el contenido. | Simples, rápidas, sorprendentemente competitivas. |
| **2. Estructurales** | Explotan el *formato* (Markdown, HTML, JSON, secciones). | La estructura ya codifica la intención del autor. Alto ROI. |
| **3. Semánticas** | Calculan dónde cambia el *significado* (embeddings o LLM) y parten ahí. | Más costosas; no siempre lo justifican. |
| **4. Avanzadas/contextuales** | **Complementan** a las anteriores enriqueciendo el chunk antes de embederlo. | Frontera del estado del arte (2024-2025). |

> **Regla de oro:** empieza con **recursive bien tuneado**. Sube de complejidad solo con evidencia medida de que no basta.

## Familia 1 — Mecánicas

> **Overlap** = solapamiento entre chunks consecutivos (típico **10-20%**) para no perder ideas en las fronteras.

**Fixed-size.** Bloques de N tokens/caracteres, con `overlap` opcional. No mira el contenido. ✅ Corpus homogéneo sin estructura (logs, streams, transcripciones planas) — buen *baseline*. ❌ Corpus con estructura (código, documentos, conversaciones): cortar a mitad de palabra degrada los embeddings de forma medible.
```python
def fixed_size_chunks(text, chunk_size, overlap):
    chunks, start = [], 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks
```

**Recursive character text splitter.** La **más usada en producción** y la de mejor balance. Jerarquía de separadores (`["\n\n", "\n", ". ", " ", ""]`); parte por el más fuerte que produzca chunks dentro del objetivo (párrafos → líneas → oraciones → caracteres). ✅ Cualquier prosa natural; el default a probar primero. ❌ Estructura jerárquica formal (JSON, código). Config que rinde: **400-512 tokens, overlap 10-20%** — sorprendentemente difícil de batir.

**Sentence-window retrieval.** Indexa **oraciones individuales** (matching preciso) pero al recuperar devuelve una **ventana ampliada** alrededor. ✅ Info concreta en oraciones específicas que necesita contexto vecinal (manuales, papers, contratos). ❌ Info distribuida en bloques (resúmenes, secciones largas). LlamaIndex `SentenceWindowNodeParser`.

**Sliding window con overlap variable.** Fixed-size donde el "paso" es independiente del overlap. Pasos pequeños → muchos chunks redundantes; grandes → pocos y dispersos (riesgo en las costuras). En la práctica, sentence-window suele ser mejor.

## Familia 2 — Estructurales

**Document-based (Markdown, HTML, JSON).** La estructura original ya codifica dónde empieza y acaba una idea (Markdown→headers, HTML→tags, JSON→jerarquía de claves).
```python
from langchain_text_splitters import MarkdownHeaderTextSplitter
markdown_splitter = MarkdownHeaderTextSplitter(
    headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3")],
)
```
Para JSON **no hay splitter genérico** que funcione: la "estructura significativa" depende del dominio (en un presupuesto, un componente; en una API spec, un endpoint) → chunker **custom** (Parte 4). ✅ Estructura explícita y fiable; **Microsoft Azure (2025): añadir el header como metadata sube la accuracy de QA 15-25 puntos.** ❌ Sin estructura (transcripciones planas, OCR malo, redes sociales).

**Hierarchical / parent-child.** Indexa chunks **pequeños** (retrieval preciso) asociados a su chunk **padre** (más grande); al recuperar pasa al LLM el hijo que coincidió **y** el contexto del padre. ✅ Documentos largos con respuesta puntual que solo se entiende con contexto amplio (manuales, libros, legales). ❌ Chunks ya pequeños y autocontenidos (FAQs, tickets). **Es una arquitectura de retrieval, no solo chunking** (decide qué se indexa —hijos— y qué se devuelve). LangChain `ParentDocumentRetriever`, LlamaIndex `HierarchicalNodeParser`.

## Familia 3 — Semánticas

**Semantic chunking.** Embeddings de oraciones consecutivas; corta donde la similitud cae bajo un umbral (*donde el significado cambia, corta*).
```python
from langchain_experimental.text_splitter import SemanticChunker
semantic_splitter = SemanticChunker(
    embeddings=OpenAIEmbeddings(model="text-embedding-3-small"),
    breakpoint_threshold_type="percentile",
    breakpoint_threshold_amount=95,
)
```
✅ Documentos multi-tema sin estructura explícita (papers, posts largos, ensayos). ❌ Documentos cortos, o alta similitud entre oraciones por diseño (jerga repetitiva, plantillas legales). **Coste oculto:** embedear **cada oración** en ingesta multiplica coste y latencia (10.000 docs × 100 oraciones = un millón de llamadas extra), y la ganancia sobre recursive bien tuneado suele ser **marginal**.

**Cluster semantic chunking.** Agrupa oraciones similares **aunque no sean consecutivas** (HDBSCAN). ✅ Discursos largos donde un tema reaparece, mesas redondas, libros con motivos recurrentes. ❌ Corpus técnicos (ideas lineales). **Rompe la trazabilidad:** un chunk clusterizado no tiene "lugar" en el original → complica citar la fuente.

**LLM-based / propositional.** La más cara y, en algunos benchmarks, la mejor. Un LLM extrae **proposiciones autocontenidas** (afirmaciones con sentido aisladas).
```
Decompose the following text into the smallest set of self-contained propositions.
Each proposition should: express a single atomic fact; be understandable without
the surrounding text; resolve all pronouns to explicit entities.
```
✅ Corpus de alto valor donde la calidad justifica un LLM por documento (documentación crítica, KB, legal). ❌ Corpus grandes (un millón de docs = cientos/miles de $ solo en chunking). En Chroma (2025), `LLMSemanticChunker` alcanzó el máximo (0.919). *"Más caro pero efectivo cuando puedes permitírtelo."*

## Familia 4 — Avanzadas y contextuales

> **No son alternativas a recursive/semantic; son complementos** que mejoran cualquier estrategia base.

**Late chunking** (Jina AI, finales 2024). **Embede el documento entero primero** (el modelo ve todo el contexto) y luego extrae los embeddings de cada chunk de la representación global. Requiere modelo con **contexto largo (8K-32K)** y token-level embeddings (`jina-embeddings-v3`, algunos de OpenAI). ✅ Cuando el significado de cada parte depende del contexto global. ❌ Modelos sin contexto largo (open source ligeros, incl. `all-MiniLM-L6-v2`). Emergente; ten el concepto presente.

**Agentic chunking.** Un agente con tool calls **decide dinámicamente** cómo partir cada sección. ✅ Corpus heterogéneo donde no quieres mantener N pipelines (enterprise con emails, contratos, papers y código). ❌ Corpus homogéneo o con restricción de coste de ingesta (los agentes son los más caros).

**Query-dependent chunking** (AI21, 2026). **Indexa varias resoluciones** del mismo documento (100/200/500/1000 tokens) y en consulta elige cuál usar (concretas→pequeños, abiertas→grandes). ✅ Mismo documento consultado de formas muy distintas. ❌ La mayoría de casos; multiplica el storage por N.

**Contextual Retrieval (Anthropic, sep 2024).** **La que probablemente vale la pena implementar de inmediato** si tu pipeline funciona pero no afina.
> **Contextual Retrieval** = antes de embedear cada chunk, lo **enriquece con un párrafo de contexto generado por un LLM** que lo sitúa dentro del documento completo.

```
<document>{whole_document}</document>
Here is the chunk we want to situate within the whole document:
<chunk>{chunk_content}</chunk>
Please give a short succinct context to situate this chunk within the overall
document for the purposes of improving search retrieval. Answer only with the
succinct context and nothing else.
```
El contexto generado se **prepende** al chunk antes de embederlo:
```
[Generated context: This chunk discusses Q3 2024 revenue figures for the European
market, mentioned in section 4.2 of the annual report.]
[Original chunk: Revenue grew by 3% over the previous quarter...]
```
- **Números de Anthropic:** **35%** menos fallos de retrieval solo con contextual embeddings; **49%** con BM25 contextual; **hasta 67%** sumando reranking. Benchmarks independientes confirman la dirección.
- ✅ Casi cualquier corpus con documentos largos donde los chunks pierden contexto al aislarse. ❌ Chunks pequeños autocontenidos (FAQs) y coste de ingesta como restricción dura.
- **Coste:** una llamada LLM por chunk. Anthropic recomienda **prompt caching** para no reenviar el documento cada vez → ~$1 por millón de tokens contextualizados.

## Cómo elegir: criterios honestos

1. **Empieza con `RecursiveCharacterTextSplitter`** (400-512 tokens, 10-20% overlap). Entre las mejores y la más barata de operar. Cambia solo con evidencia medida.
2. **Si hay estructura explícita (Markdown, HTML, JSON), úsala.** Document-based + metadata enriquecido = mayor ROI conocido (Azure: +15-25 puntos).
3. **Si los chunks pierden sentido al aislarse → Contextual Retrieval.** La más madura de las "avanzadas".
4. **Semantic/LLM-based son legítimas pero caras.** Justifícalas con datos sobre tu corpus, no por un blog.
5. **Parent-child es arquitectura, no solo chunking.** No la metas si tu pipeline aún no funciona plano.
6. **Late/agentic/query-dependent son emergentes.** No las metas en producción sin caso que las justifique. *La novedad no es una ventaja en sí.*
7. **Lo más importante: el mejor chunking depende del tipo de documento.** Un corpus heterogéneo casi siempre se beneficia de **distintas estrategias para distintos tipos** — exactamente el proyecto (Parte 4).

---

# Parte 4 — Chunking del proyecto: presupuestos JSON y transcripciones

> Aterriza el catálogo de la Parte 3 a los **dos tipos de documento reales** del proyecto, con propiedades radicalmente distintas.

| Tipo | Estructura | Unidad lógica | Estrategia correcta |
|---|---|---|---|
| **Presupuestos (JSON)** | Jerárquica explícita, esquema predecible | El **componente** | Estructural (respeta la jerarquía JSON) |
| **Transcripciones** | Texto plano ~45 min, sin estructura | El **bloque temático** | Semántica (topic-based segmentation) |

## Dos tipos, dos chunkers

**Dos chunkers especializados que comparten una interfaz común**, no uno genérico con condicionales. *Si dos entradas requieren tratamiento radicalmente distinto, es más limpio dos implementaciones explícitas.*

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
La interfaz común hace cada chunker **testeable por separado** y abre la puerta a más estrategias en vivo. Ambos son del **servicio IA (Python + FastAPI)**; el backend de negocio (Rails de referencia) solo invoca el endpoint de ingesta.

## El chunker JSON estructural

**Por qué los splitters genéricos fallan** con un presupuesto JSON:
1. Tratan llaves/comillas/comas como caracteres normales → cortan a mitad de clave (`"client_metadata": {"sector":` | `"finance", "country":`). El embedding es **ruido**.
2. Aunque el corte caiga bien, **se pierde la jerarquía padre-hijo**: un chunk `"OAuth 2.0 backend"` sin cliente/sector/año competirá con cientos de auth de sectores irrelevantes.
3. Serializar el JSON a texto plano antes de chunkear pierde la jerarquía explícita.

**Tres decisiones de diseño:**

- **Granularidad: un componente = un chunk.** No el presupuesto entero (pierde especificidad) ni cada campo suelto (pierde coherencia). El componente = **unidad de razonamiento del dominio**.
- **Contenido: texto legible enriquecido con contexto del padre.** El campo `text` (lo que se embede) **no es el JSON crudo**, sino:
  ```
  [Project: Mobile banking API with OAuth 2.0 authentication and PSD2...]
  [Client sector: finance | Year: 2024 | Main tech: ruby_on_rails]

  Component: OAuth 2.0 authentication backend
  Description: Implementation of OAuth 2.0 flows with JWT-based session...
  Tech stack: ruby_on_rails, postgresql, redis
  Complexity: high
  Estimated hours: 120
  ```
  > **Contextual chunk header** = info del documento padre prepended al texto del chunk antes de embederlo.

  Las dos líneas entre corchetes son contextual chunk headers: la **versión estática y barata** de Contextual Retrieval (Parte 3) — usa el contexto que ya está en el JSON **sin llamar a un LLM**. Palanca de mayor ROI conocida.
- **Metadata: campos filtrables que NO se embeden.** Sector, año, tecnología, complejidad, horas → `metadata`. Para **filtrar** (`sector = 'finance' AND year >= 2023`) y **devolver info estructurada** sin parsear texto.

```python
@dataclass
class Chunk:
    chunk_id: str
    text: str
    metadata: dict[str, Any]
    token_count: int   # vía tiktoken
```
> **Trabajo del ejercicio (production-ready):** validación Pydantic del schema de entrada (un campo faltante no debe tirar `KeyError` opaco), logging estructurado por presupuesto, caso límite "componente con descripción anormalmente larga", e integración con `POST /embeddings/ingest`. El esqueleto es el chasis; esas decisiones las tomas tú.

## El segmentador por temas (transcripciones)

**Por qué los splitters de carácter destrozan una transcripción:** 6.000-12.000 tokens, **cero estructura formal**, hablantes alternados (`Speaker A:`), temas que se interrumpen y vuelven 10 min después, mucho contenido de baja densidad. Un `RecursiveCharacterTextSplitter` corta a mitad de intervención.

> **Topic-based segmentation** (familia semántica) = embede oraciones/intervenciones consecutivas, detecta dónde la similitud entre vecinos cae bajo un umbral, y parte ahí → chunks que coinciden con **bloques temáticos coherentes**.

**Tres decisiones** (paralelas a las del JSON, razonamiento distinto):
- **Granularidad: cada bloque temático = un chunk.** No por oración (pequeño) ni por minuto (no respeta el contenido). Se segmenta **donde el tema cambia**; la duración varía (30 s a 8 min). Se ajusta al contenido, no al reloj.
- **Contenido: el bloque con su contexto de reunión** (metadata prepended: cliente, fecha, participantes, fase).
  ```
  [Meeting: Requirements gathering · 2024-03-15]
  [Client: FintechCorp · Phase: discovery]
  [Speakers: Antonio (consultant), Maria (CTO), Pedro (lead dev)]

  Topic block: Authentication and security
  Maria: We need OAuth 2.0 with refresh tokens, and we need it to work with our SAML provider...
  ```
- **Metadata: información temporal y de hablante** (posición early/mid/late, timestamp si lo hay, hablante dominante, tema). Filtros: fecha, cliente, fase.

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
> **Dos sutilezas:**
> - `similarity_threshold = 0.55` es **punto de partida, no universal**. Alto → demasiados bloques; bajo → bloques enormes. Depende del modelo y del estilo; se calibra en vivo.
> - La segmentación interna usa **`all-MiniLM-L6-v2` local** aunque el resto del sistema use `text-embedding-3-small`: hay que embedear muchas oraciones rápido y barato; un local de 384 dims es perfecto, mientras que la API por oración sería caro y lento. **Distintas piezas del pipeline pueden usar distintos modelos de forma legítima.**

## Metadata enrichment: la palanca subestimada

El hallazgo de Azure (metadata estructural **sube la accuracy de QA 15-25 puntos** sin tocar nada más) es de mejor relación esfuerzo/impacto. Ambos chunkers lo hacen de **tres formas**:

| Forma | Qué es | Para qué |
|---|---|---|
| **1. Headers contextuales DENTRO del texto** | el bloque entre corchetes que se embede | el vector incorpora esa info en su geometría |
| **2. Metadata estructurada FUERA del texto** | el dict `metadata`; no se embede pero viaja con el chunk | filtrar: [Sesión 8](../session-08-datadrivenai-bbdd-vectoriales/session-08-theory-datadrivenai-bbdd-vectoriales.md) combina búsqueda vectorial + filtros SQL (*"auth para fintech del último año"* = parte semántica + `client_sector = 'finance' AND year >= 2024`) |
| **3. IDs trazables** | `{budget_id}::{component_id}`, `{meeting_id}::{block_index}` | citar fuente, auditar, invalidar chunks cuando el padre cambie |

> **Regla — ¿texto o metadata?** Si **cambia el significado semántico** para una consulta natural (el sector distingue "auth fintech" de "auth e-commerce") → **texto**. Si es **discreta y para filtrar** (`year`, `complexity`, `estimated_hours`) → **metadata**. A veces ambos (el sector pesa semánticamente **y** filtra): cada copia cumple un rol distinto.

## Composición en el servicio IA (IngestRouter)

`POST /embeddings/ingest` recibe `document_type` en el body y enruta:

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

**Flujo:** Backend `POST /embeddings/ingest` (con `document_type`) → `IngestRouter` → `JSONStructuralChunker` **o** `TopicSegmentationChunker` → ambos convergen en un **`OpenAIEmbedder` compartido** (`text-embedding-3-small`, batch, 1536 dims) → `IngestResponse` → **PostgreSQL + pgvector** (Sesión 8).

> **Decisión explícita:** se podría **detectar el tipo automáticamente**, pero "explícito por payload" es más simple y auditable. La detección automática es **agentic chunking** (Parte 3): legítima, pero con coste que aquí no se justifica. Que el backend sea Rails es **accidental**: el contrato entre capas es REST simple, independiente del stack.

---

# Glosario rápido

| Término | En una frase |
|---|---|
| **Embedding** | Vector de números reales de dimensión fija que representa un texto; parecidos → cercanos. |
| **Aprendizaje contrastivo** | Entrenamiento con tripletes (ancla/positivo/negativo) que induce la geometría semántica. |
| **Similitud coseno** | Mide el ángulo entre vectores, ignora la magnitud. La métrica más común para texto. |
| **Producto escalar (dot product)** | Numerador del coseno; idéntico al coseno si los vectores están normalizados, más barato. |
| **Normalización** | Llevar un vector a longitud 1. Muchas BBDD lo asumen; comprueba norma ~1.0. |
| **MTEB** | Massive Text Embedding Benchmark. Referencia de facto, pero mide promedios generalistas. |
| **Matryoshka (MRL)** | Entrenamiento que permite truncar el vector a menos dims conservando casi toda la calidad. |
| **Chunking** | Partir documentos en trozos antes de embederlos. La decisión de mayor impacto en el retrieval. |
| **Overlap** | Solapamiento entre chunks consecutivos (10-20%) para no perder ideas en las fronteras. |
| **Contextual chunk header** | Info del documento padre prepended al chunk antes de embederlo (alto ROI). |
| **Contextual Retrieval** | Técnica de Anthropic: enriquecer cada chunk con contexto generado por LLM antes de embederlo. |
| **BM25** | Métrica clásica de búsqueda por términos exactos (TF-IDF). Complementa embeddings (hybrid search). |
| **Maldición de la dimensionalidad** | En muchas dims las distancias se concentran; por eso `sim` 0.2-0.5 entre no-relacionados es normal. |

---

# Cómo conecta con nuestro ejercicio

Base de la parte de **ingesta y recuperación** del estimador:

- **Modelo:** `text-embedding-3-small` (1536 dims, normalizado → coseno/dot intercambiables).
- **Dos chunkers** con interfaz común: `JSONStructuralChunker` (presupuestos, 1 componente = 1 chunk con contexto del padre) y `TopicSegmentationChunker` (transcripciones, bloques temáticos con `all-MiniLM-L6-v2` local).
- **Metadata enrichment** en texto (headers contextuales) **y** fuera (campos filtrables + IDs trazables).
- **`IngestRouter`** que enruta por `document_type` hacia un `OpenAIEmbedder` compartido.
- Persistencia y búsqueda semántica con filtros SQL → **[Sesión 8 — pgvector](../session-08-datadrivenai-bbdd-vectoriales/session-08-theory-datadrivenai-bbdd-vectoriales.md)**.

> **El hilo conductor:** no hay configuración universal. Modelo, métrica y sobre todo chunking se eligen **midiendo sobre tus propios datos** — los benchmarks y los blogs son el mapa, no el territorio.
