# Sesión 09 — Del CAG estático al flujo RAG (versión clara)

> Versión simplificada del resumen de los 5 artículos de la Sesión 9.
> Misma información, menos paja. Cada término técnico se explica en una frase.
> **Hilo conductor:** un sistema que busca presupuestos antiguos parecidos para estimar un proyecto nuevo. La S9 es la primera del módulo de RAG; la S10 (reranking, híbrida) y la S11 (evaluación) siguen refinando el retrieval.

---

## Glosario base (léelo una vez y vuelve cuando haga falta)

| Término | Qué es, en una frase |
|---|---|
| **CAG** (Cache-Augmented Generation) | Meter todo el conocimiento (los ~30 presupuestos) **dentro del prompt** de una vez, para siempre. |
| **RAG** (Retrieval-Augmented Generation) | En cada petición, **buscar** los documentos relevantes y pasárselos al modelo. |
| **Embedding** | Convertir un texto en una lista de números (un "vector") que captura su significado. Textos parecidos → vectores cercanos. |
| **Chunk** | Un trozo de documento (un párrafo, una sección). Indexamos chunks, no documentos enteros. |
| **Retrieval (recuperación)** | La etapa que busca los chunks relevantes en la base vectorial. |
| **Similitud / distancia coseno** | La forma de medir cuán cerca están dos vectores. Distancia pequeña = muy parecidos. |
| **Top-K** | Cuántos chunks devuelve la búsqueda (top-10 = los 10 más cercanos). |
| **Threshold (umbral)** | Distancia máxima que aceptamos: por encima, el chunk es demasiado distinto y se descarta. |
| **Recall** | ¿De todo lo relevante que existe, cuánto trajiste? |
| **Precision** | ¿De lo que trajiste, cuánto era relevante de verdad? |
| **Grounding** | Obligar al modelo a apoyarse **solo** en el contexto recuperado, no en su conocimiento general. |
| **Alucinación** | Que el modelo se invente datos (un número, una cita) sin fundamento real. |
| **pgvector** | Extensión de PostgreSQL que guarda vectores y los busca por distancia. |
| **Metadata** | Datos *sobre* el documento que no están en su texto: sector, año, tecnología. |

---

## La idea en una página

Hasta ahora el sistema funcionaba con **CAG**: metíamos ~30 presupuestos históricos dentro del prompt y el modelo estimaba apoyándose en ellos. Funciona mientras el cliente pida algo parecido a esos 30 ejemplos. En cuanto menciona algo nuevo ("un marketplace sanitario en Alemania con KYC reforzado por la BaFin"), el modelo **se inventa un número**. Y el conocimiento está **congelado**: añadir un presupuesto exige reescribir el prompt y redesplegar.

> CAG es estudiar memorizando 30 fichas y rezar para que el examen caiga ahí. **RAG es ir al examen con acceso a la biblioteca y saber buscar la ficha justa para cada pregunta.**

Ese "buscar cada vez" se descompone en **cuatro etapas encadenadas** (la nomenclatura del paper de Lewis et al. 2020, que ha aguantado pese a todas las variantes modernas — Agentic RAG, GraphRAG, Self-RAG):

1. **Query** — convertir la entrada del usuario en algo buscable.
2. **Retrieval** — encontrar los chunks relevantes en la base vectorial.
3. **Augmentation** — ensamblar esos chunks en un bloque de contexto que el modelo entienda.
4. **Generation** — llamar al LLM con ese contexto y un prompt que le obligue a usarlo.

> **El mantra del módulo:** *"no amount of prompt engineering fixes bad retrieval"* — **ningún prompt arregla un mal retrieval.** El techo de calidad de todo el sistema lo fija la etapa de Retrieval; por eso este módulo le dedica casi todo el esfuerzo.

RAG no es "mejor" que CAG en abstracto: es **distinto**, a cambio de más complejidad, latencia y coste por petición. Para nuestro proyecto está justificado porque el corpus **crece con el tiempo y no cabe completo en contexto**.

---

# PARTE 1 — Del CAG estático al flujo RAG

## 1.1 El techo del CAG

Tiene dos caras:

- **Conocimiento congelado.** Añadir un presupuesto exige editar el prompt y redesplegar.
- **Límite de contexto.** 800 presupuestos × ~3.000 tokens = 2,4 M tokens: no caben en ninguna ventana. Los que no metiste quedan fuera del alcance del modelo **para siempre**.

Ante algo no cubierto, el modelo inventa apoyándose en su conocimiento genérico, o produce un número razonable **sin fundamento en datos de la empresa**. Ambas inaceptables para un estimador serio.

## 1.2 Las cuatro etapas son cuatro puntos de fallo

Cada etapa hace **trabajo real** y puede degradar la calidad:

- **Query.** La entrada no es una pregunta limpia: es una transcripción de miles de tokens con ruido, divagaciones y anáforas. Embeberla directa produce un vector "promediado" que apenas discrimina. Esta etapa extrae los requisitos clave y genera consultas optimizadas (→ Parte 2).
- **Retrieval.** Recibe queries optimizadas y devuelve los chunks más relevantes. La versión naive (top-K por coseno, sin filtros ni umbral) de la S8 se queda corta. **Es la etapa de mayor impacto** (→ Parte 3).
- **Augmentation.** Ensambla los chunks. El reflejo ingenuo — concatenar con un separador — es justo lo que produce alucinaciones y citas inventadas (→ Parte 4).
- **Generation.** La llamada al LLM con un prompt que fuerza grounding, define qué hacer ante contexto insuficiente y permite validar citaciones (→ Parte 4).

En código, el orquestador son **cinco líneas**, y cada una es una decisión de diseño:

```python
async def estimate_from_transcript(transcript: str) -> EstimateResponse:
    structured_query = await query_reformulator.reformulate(transcript)
    chunks = await retriever.search(
        query=structured_query, top_k=10, threshold=0.65,
        filters=structured_query.metadata_filters,
    )
    context = context_assembler.assemble(chunks, max_tokens=4000)
    estimate = await generator.generate(
        transcript=transcript, context=context, schema=EstimateSchema,
    )
    return estimate
```

**Impacto en la estructura.** El pipeline añade dos carpetas sobre el cierre de S8, sin tocar las existentes:

```
ingest/ (S06)  ·  embedding_pipeline/ (S07)  ·  storage/ (S08)   ← dependencias estables
retrieval/    ← query_reformulator.py, retriever.py              ← NUEVO
generation/   ← context_assembler.py, prompt_builder.py, estimator.py  ← NUEVO
```

Esa separación permite que el retriever evolucione en la S10 (reranking) sin tocar la generación, y al revés.

## 1.3 CAG vs RAG: las cinco diferencias que importan

| Dimensión | CAG | RAG |
|---|---|---|
| **Frescura** | Estática, *redeploy* | Incremental, en vivo (`POST /insert` al cerrar venta) |
| **Techo del corpus** | ~400k tokens (gpt-5) | Ilimitado; escala con tu empresa, no con el modelo |
| **Latencia y coste** | 1 llamada, bajo (prompt caching) | 3–4 llamadas, medio (puede ser 3–4× CAG) |
| **Trazabilidad** | Difusa, inexplicable | Precisa, citable (qué se recuperó, qué contexto, qué estimación) |
| **Resistencia a alucinación** | Baja | Alta con grounding (reduce, no elimina) |

> En una frase: **CAG asume que el contexto correcto está siempre disponible porque lo elegiste por adelantado; RAG asume que hay que ir a buscarlo cada vez y que esa búsqueda es el corazón del sistema.** Más robusto, pero más complejidad. No hay almuerzo gratis.

La diferencia de **frescura justifica RAG por sí sola** en cualquier empresa que cierre proyectos con regularidad. Donde RAG **pierde** es en latencia/coste, y conviene reconocerlo.

## 1.4 Cuándo CAG sigue siendo la respuesta correcta

> **CAG no es universalmente peor.** El paper *"Don't Do RAG"* (Chan et al., 2024) demostró que **con corpus pequeño y estable, CAG produce mejores respuestas** en métricas de QA: el modelo "ve" todo el corpus en una atención completa, mientras RAG ve un subconjunto elegido por un retriever **que puede equivocarse**.

- **CAG gana** para corpus < ~100k tokens efectivos, estables, donde el coste por petición importa y la trazabilidad no es crítica: FAQs internas, docs de producto que cambian poco, herramientas legales sobre un cuerpo normativo fijo.
- **Tercera vía híbrida:** contexto base estable (políticas, plantillas JSON, reglas) por **CAG** en el system prompt + contexto variable (presupuestos similares) por **RAG**. Siguiente paso de optimización, pero su complejidad no se justifica para el alcance del programa.

## 1.5 El retrieval domina

> *"No amount of prompt engineering fixes bad retrieval."* — describe el modo de fallo más común en producción.

Si el retrieval devuelve los chunks correctos, incluso un prompt mediocre produce respuestas decentes. Si devuelve chunks irrelevantes, **ningún prompt te salva**.

**Orden de prioridades cuando un RAG falla** (siempre el mismo):

1. ¿Recupero los chunks correctos? Si no, todo lo demás es ruido.
2. ¿Ensamblo bien el contexto? (Llegan pero el modelo los ignora → Augmentation.)
3. ¿El prompt fuerza grounding?
4. **Solo en último lugar:** ¿el modelo es suficientemente capaz?

> La tentación de empezar por el modelo es fuerte y **casi siempre equivocada**. El palanqueo está en la ingeniería de retrieval.

---

# PARTE 2 — Reformulación de queries

> **Para cualquiera:** la primera tentación al recibir una transcripción real es embeberla tal cual. No funciona, y no por magia matemática: una transcripción es ruido conversacional con las palabras importantes enterradas. Hay que **destilarla** antes de buscar. Esa capa de destilado es lo que más impacta en el *recall*.

## 2.1 Por qué embeber la transcripción cruda falla

Tres cosas rompen la búsqueda:

1. **La longitud disuelve la señal.** Tus chunks son de ~300 tokens, muy específicos. Embeber 2.000 tokens con cinco temas mezclados da el **centroide de cinco regiones**: un punto "en medio de todas y cerca de ninguna". Las distancias se comprimen en un valor medio mediocre.
2. **El ruido ahoga las keywords.** Las palabras que discriminan ("marketplace", "Stripe Connect", "KYC", "BaFin", "SAP") quedan enterradas entre conectores ("pues mira", "lo nuestro", "no es un Amazon"). El embedder no sabe cuáles importan.
3. **Las anáforas no significan nada.** "Lo que hablábamos el otro día", "como me decíais" se apoyan en contexto que no está en la transcripción, **contaminando el vector con señal que no remite a nada**.

> Sin una capa que convierta la transcripción en algo buscable, **ningún ajuste de top-K, threshold o reranker te salva** de la entrada degradada.

## 2.2 Las cinco familias de reformulación

> **Recall** = cuánto de lo relevante traes. **Filtros** = condiciones estructurales (sector, año) que restringen qué chunks son candidatos.

| Técnica | Coste | Recall | ¿Produce filtros? |
|---|---|---|---|
| Query rewriting | Bajo | Bajo a medio | No |
| Sub-query decomposition | Alto | Alto pero ruidoso | No |
| Step-back prompting | Bajo | Variable | No |
| HyDE | Medio | Alto | No |
| **Extracción estructurada** | Medio | Alto | **Sí** |

> **Query rewriting** = pedir al LLM una "consulta técnica concisa". Funciona con entradas cortas mal formuladas; falla con entradas largas multi-tema.
> **Sub-query decomposition** = el LLM parte la entrada en varias sub-queries, cada una se busca y los resultados se fusionan (con **Reciprocal Rank Fusion / RRF**). Mejora recall pero multiplica coste y complejidad.
> **Step-back prompting** = subir un nivel de abstracción antes de buscar. Brilla en QA sobre conocimiento estructurado; rinde peor en dominios *narrow* como estimación. Apenas se toca.
> **HyDE (Hypothetical Document Embeddings)** = en vez de embeber la pregunta, pides al LLM una **respuesta hipotética** (un documento ficticio) y embebes eso. Insight: un documento sintético se parece más a tus documentos que una pregunta corta. Falla cuando el modelo alucina tecnologías que tu empresa nunca usó.

## 2.3 La elección del programa: extracción estructurada

Pides un **objeto estructurado**: un JSON validable contra un esquema explícito.

```python
class EstimationQuery(BaseModel):
    function: str = Field(description="Primary product function in 3-8 words")
    technologies: list[str] = Field(default_factory=list)
    sector: str | None = Field(default=None)
    scale: Literal["pilot", "small", "medium", "large"] | None = Field(default=None)
    country: str | None = Field(default=None)
    regulations: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
```

> **Responses API** = la API de OpenAI para generar; con `text.format` de tipo `json_schema` y `strict: True` el modelo no se desvía del esquema.

```python
async def reformulate(transcript: str) -> EstimationQuery:
    response = await client.responses.create(
        model="gpt-5-mini",
        input=[{"role": "system", "content": REFORMULATION_SYSTEM_PROMPT},
               {"role": "user", "content": transcript}],
        text={"format": {"type": "json_schema", "name": "EstimationQuery",
            "schema": EstimationQuery.model_json_schema(), "strict": True}},
    )
    return EstimationQuery.model_validate_json(response.output_text)
```

El system prompt instruye a extraer **solo lo explícitamente mencionado o inequívocamente inferible** y dejar lo demás en `null`. La tentación de "rellenar con sentido común" (inferir GDPR porque hay datos personales) es la **principal fuente de errores en producción**.

El objeto se usa de **dos maneras** — y ahí está su ventaja sobre las otras cuatro, que no producen estructura aprovechable:

1. **Sus campos textuales se componen en un texto sintético** que se embebe (similar a HyDE pero controlado):

   ```python
   def compose_search_text(q: EstimationQuery) -> str:
       parts = [q.function]
       if q.technologies: parts.append(f"with {', '.join(q.technologies)}")
       if q.sector:        parts.append(f"for the {q.sector} sector")
       if q.country:       parts.append(f"in {q.country}")
       if q.regulations:   parts.append(f"compliant with {', '.join(q.regulations)}")
       if q.constraints:   parts.append(f"requiring {', '.join(q.constraints)}")
       return ". ".join(parts) + "."
   # → "B2B payments marketplace platform. with Stripe Connect, KYC, SAP.
   #    for the healthcare sector. in Germany. compliant with BaFin..."
   ```

2. **Sus campos categóricos se usan como filtros de metadata en pgvector** (`sector = "healthcare"`). Información que **se pierde en cualquier otra técnica**.

> La mejora en recall sobre la misma base es **típicamente 2×–5×**.

**Por qué se elige (no por ser la más sofisticada):** HyDE da vectores algo mejores en benchmarks, pero extracción estructurada gana en cuatro dimensiones de producción: **coste predecible** (JSON de 50–100 tokens vs 200–400 de HyDE), **latencia predecible** (una llamada), **debugabilidad** (única que produce un artefacto inspectable: ves si confundió el sector) y **utilidad downstream** (alimenta los filtros).

**Fallback.** Si la validación del JSON falla, el sistema cae a **query rewriting puro**. Peor que extracción, mejor que la transcripción cruda. **Debe activarse y registrarse:** si nunca se activa, el reformulador es demasiado tolerante; si se activa **>5 %**, hay un problema sistemático con el prompt o el esquema.

## 2.4 Trade-offs honestos

- **Subir a HyDE** tiene sentido con corpus muy descriptivo y modelo que conoce bien el dominio (docs médicas/jurídicas). Para chunks semi-formales, beneficio **marginal**.
- **Subir a sub-query decomposition** tiene sentido cuando las transcripciones son consistentemente multi-tema y los temas **ortogonales**. La extracción ya captura esas dimensiones en campos del JSON.
- **Subir a híbrida** (extracción para filtrar + HyDE para la búsqueda, en paralelo) es la evolución razonable si el recall se queda corto tras semanas de uso. No la elección inicial.

> **Lo que no compensa** es complicar el reformulador **antes de medir**. Empezar por HyDE "porque suena mejor" lleva a sistemas complejos con mejoras marginales que ni se pueden medir (no había baseline simple). Regla: **construir lo más simple, instrumentarlo, medir sobre transcripciones reales, y solo entonces decidir** si la complejidad se justifica.

La reformulación **no es un detalle del retriever**: es una capa con prompt versionado, esquema versionado, instrumentación y *test suite*. La mayoría de regresiones de calidad vendrán de alguien que edita el prompt para arreglar un caso y rompe diez sin enterarse. Esa fragilidad es la contrapartida de poner un LLM en la entrada.

---

# PARTE 3 — Retrieval que no es solo coseno: top-K, threshold y filtros

> **Para cualquiera:** la búsqueda por similitud de la S8 pide "los K más parecidos" y ya. Esto añade dos disciplinas: un **umbral de calidad** (no metas basura aunque falten resultados) y **filtros estructurales** (no mezcles peras con manzanas), con operadores que pgvector ya ofrece.

## 3.1 Las dos sorpresas del retrieval naive

- **Resultados clónicos.** Pides 10 chunks; 8 son del **mismo** presupuesto. Solo había un proyecto similar y, como `top-K=10` exige diez, se rellena con chunks repetidos. Tu estimación está fundada en **un solo caso, no en diez**.
- **Resultados mediocres.** No hay presupuestos genuinamente similares. Devuelve diez, pero todas las distancias están comprimidas en **0.7–0.8**: ninguno es realmente parecido. Cumple la promesa literal pero la estimación es una **alucinación apoyada en parecidos genéricos**.

> Causa común: el retriever usa **una sola palanca** (`top-K`) y le faltan **calidad mínima** (umbral) y **filtrado estructural** (no todo chunk es candidato para toda query).

## 3.2 Top-K y sus tres sesgos

`top-K` define cuántos chunks devuelve, ordenados por distancia ascendente. El reflejo al ver resultados pobres es **subir K**. A veces funciona, pero trae tres consecuencias medibles:

1. **El coste del prompt crece casi lineal con K.** Cada chunk son 200–400 tokens; de K=10 a K=30 añade 4.000–8.000 tokens. Si una generación cuesta ~0,50 € con K=10, con K=30 cuesta ~1,50 €. Multiplícalo por miles de peticiones/mes.
2. **El ruido degrada la calidad.** Por *lost in the middle* (→ Parte 4), 30 chunks parcialmente relevantes hacen que el modelo ignore la mayoría. El chunk crítico en posición 14 recibe menos atención que el irrelevante en posición 1.
3. **Subir K oculta el problema.** Si solo hay 3 chunks similares y pides 10, haces el mismo retrieval **con 7 distracciones**. El sistema te dice "no hay más material" y la respuesta correcta es **propagar esa señal**, no disfrazarla.

> **Regla:** `K` **moderado y estable** (10 es razonable) y que el **threshold** descarte lo que no merece entrar. El número de chunks por petición no es fijo: es un **emergente** del threshold sobre los K candidatos — a veces 10, a veces 3, a veces **0**. Y cero es información válida, no un fallo.

## 3.3 Threshold: la disciplina que falta

> **Threshold** = la distancia máxima aceptable. En pgvector `<=>` da distancia coseno entre 0 (idénticos) y 2 (opuestos); para embeddings de OpenAI el umbral típico está entre **0.5 y 0.7**.

**El número no se decide por intuición, sino mirando la distribución empírica.** Procedimiento: coges 20–30 transcripciones, las pasas por el reformulador, ejecutas con `K=50` **sin threshold** y graficas las distancias. Verás dos grupos: uno pequeño de distancias bajas (≈0.3–0.5) que a inspección manual son **relevantes**, y uno grande en **0.7–0.9** que es **ruido**. El threshold va en el **valle entre los dos**; para `text-embedding-3-small` sobre corpus especializado, ese valle cae en **0.6–0.65**.

```sql
SELECT c.id, c.content, c.metadata,
       c.embedding <=> :query_embedding AS distance
FROM chunks c
WHERE c.embedding <=> :query_embedding < :distance_threshold
ORDER BY c.embedding <=> :query_embedding
LIMIT :top_k;
```

> **Trampa operativa (HNSW).** El `WHERE` y el `ORDER BY` usan la misma distancia, pero el planner solo reutiliza el índice **si la operator class está alineada con el operador de la query** (`vector_cosine_ops` ↔ `<=>`). Si fuera `vector_l2_ops` con una query `<=>`, el índice **no se aplica**, cae a *sequential scan* y la búsqueda pasa de milisegundos a segundos. Es el antipatrón silencioso de la S8, y la condición previa para que cualquier ajuste de threshold funcione.

> **Si ningún chunk supera el threshold → soft-fail.** El endpoint devuelve **lista vacía** + `low_confidence: true`. El orquestador **no llama al generador con contexto vacío** (eso invita a alucinar): responde *"no hay evidencia suficiente para estimar este proyecto; revisar manualmente"*. Reconocer los límites y comunicarlos hacia arriba es lo que distingue un RAG serio de uno didáctico.

Alternativa: **relajar el threshold dinámicamente** (empezar en `0.55`, y si devuelve <3 chunks relajar a `0.65` y repetir). Válida, pero introduce no-determinismo y dificulta el debug; el programa no la adopta por defecto.

## 3.4 Filtros de metadata: tres estrategias en pgvector

La similitud captura parecido semántico pero **ignora datos estructurales** críticos: si la transcripción es de salud no quieres chunks de retail aunque sean cercanos; si el proyecto es para el año que viene, no lo ancles en presupuestos de 2019 con tecnología obsoleta. Tres patrones:

- **Pre-filtering.** Aplica el `WHERE` estructural **antes** de la búsqueda vectorial.

  ```sql
  SELECT c.id, c.content, c.metadata, c.embedding <=> :query_embedding AS distance
  FROM chunks c JOIN documents d ON c.document_id = d.id
  WHERE d.sector = ANY(:sectors)
    AND d.project_year >= :year_min
    AND c.embedding <=> :query_embedding < :distance_threshold
  ORDER BY c.embedding <=> :query_embedding LIMIT :top_k;
  ```

  **Correcto con filtro de alta selectividad** (deja un subconjunto pequeño). Antes se decía que pre-filtering "destruía el índice HNSW"; **desde pgvector 0.7 los *iterative scans*** navegan el grafo descartando lo que no cumple el `WHERE`. Ya no es catastrófico y para selectividades <20 % rinde bien. **Estrategia por defecto.**

- **Post-filtering.** Busca con `K` ampliado (`wide_k = top_k × 3`) y **después** aplica el `WHERE`. Correcto con filtro de **baja selectividad**. **Riesgo:** perder recall si el filtro es muy selectivo (si `wide_k=50` pero solo 2 cumplen, fallaste); sin instrumentación no te enteras.

- **In-query filtering.** Se escribe como pre-filtering pero **el optimizador decide internamente** la estrategia según la selectividad. El "pre vs post" pasa a ser decisión del planner. **Es la query de producción.**

**Los cuatro filtros que expone la API:** `sectors`, `project_year_range`, `tech_stack` (operador JSONB `@>` sobre metadata) y `chunk_types` (tipos del esquema S7: `scope_block`, `line_item`, `phase`). El patrón `(:filter IS NULL OR ...)` los hace **opcionales**: si el reformulador no extrajo el campo, viene `null` y se ignora. **Encadena directo con la salida estructurada de la Parte 2:** cada campo Pydantic mapea a un filtro opcional.

## 3.5 Cuatro anti-patrones

1. **Subir K para arreglar calidad.** La solución no es traer *más*, es traer *mejor*. Subir K solo si una inspección manual confirma que hay relevantes más allá del top-10.
2. **Confiar en el LLM como filtro final** ("metemos 20 y que elija"). El modelo **no es un buen retriever**: no compara sistemáticamente ni rechaza lo irrelevante con disciplina. **El filtrado se hace en el retriever; el LLM sintetiza, no filtra.**
3. **Omitir el threshold porque "casi siempre hay algo".** El día que falle, generará una estimación basada en ruido y nadie lo notará hasta que un cliente lo cuestione.
4. **Mezclar `chunk_types` sin filtrar.** Un `scope_block` y un `line_item` tienen utilidades distintas. Filtrar por tipo cuando el reformulador da pistas **es gratis y mejora la precisión**.

## 3.6 Recall vs precision: el trade-off real

> **No se pueden maximizar a la vez.** Recall = recuperar todo lo potencialmente relevante (con ruido). Precision = recuperar solo lo claramente relevante (dejando fuera alguna joya).

- RAG **didáctico** → prioriza **recall** (más material para el LLM).
- RAG **de producción con consecuencias económicas** → prioriza **precision**: traer menos pero mejor, aceptar el "no tengo evidencia suficiente", y dejar para la S10 (reranking) los mecanismos que suben recall sin perder precision.

> **Asimetría de errores:** una alucinación apoyada en parecidos (estimar 250.000 € sin evidencia) es **más peligrosa** que un "no lo sé" honesto. La primera crea una expectativa imposible de honrar; el segundo preserva la confianza. Eso justifica favorecer precision en este dominio.

---

# PARTE 4 — Augmentation y generación: ensamblar contexto y forzar grounding

> **Para cualquiera:** ya tienes los chunks correctos. Falta "dárselos" al modelo. La forma ingenua — pegarlos uno tras otro — es justo la que produce respuestas inventadas. Esto cubre cómo **empaquetar** el contexto (etiquetas, orden, recorte) y cómo **instruir** al modelo (usa solo esto, cita las fuentes, di "no sé").

## 4.1 Por qué `"\n\n".join(chunks)` falla

```python
context = "\n\n".join([chunk.content for chunk in retrieved_chunks])
prompt = f"Contexto:\n{context}\n\nGenera una estimación para: {query}"
```

No lanza excepción, pero produce con regularidad **tres patologías**:

1. **Citas inventadas.** Sin instrucciones de cómo referenciar, el modelo fabrica IDs plausibles ("según el proyecto 312…") que no estaban.
2. **Mezclas cruzadas.** Combina chunks distintos como si fueran un único proyecto.
3. **Respuesta sin contexto** (la más sutil): **ignora silenciosamente** los chunks y responde con su conocimiento general, dándote la falsa impresión de que el retrieval funcionó.

> Causa común: el modelo **no ha recibido instrucciones** sobre cómo tratar el bloque. Augmentation no es "meter chunks en el prompt"; es construir un input que le diga explícitamente qué es autoritativo, si puede negarse, y qué fuente atribuir a cada afirmación.

## 4.2 Delimitadores XML

Los modelos modernos están entrenados con mucho XML y reconocen etiquetas como `<source>` como **límites semánticos**. El ensamblado vive en `generation/context_assembler.py`:

```python
def build_context_block(chunks: list[RetrievedChunk]) -> str:
    blocks = []
    for chunk in chunks:
        attrs = (f'id="{chunk.id}" sector="{chunk.sector}" '
                 f'project_year="{chunk.project_year}" '
                 f'chunk_type="{chunk.chunk_type}" distance="{chunk.distance:.3f}"')
        blocks.append(f"<source {attrs}>\n{chunk.content.strip()}\n</source>")
    return "\n\n".join(blocks)
```

Tres decisiones:

- **Metadata como atributos XML, no embebida en el texto.** Permite citar con precisión ("según `source id=142`") sin que el modelo la parsee cada vez.
- **Se incluye la `distance`.** Debatible (algunos la ocultan para que no se sobreajuste), pero da al modelo una **señal explícita de relevancia**.
- **El delimitador es `<source>` en singular**, no `<context>` ni `<document>`: el modelo trata cada `<source>` como **unidad atribuible de información**, justo lo que fuerza citaciones.

> Alternativa: **JSON delimited context**. Funciona, pero los modelos tienden a "leer" JSON como **datos a interpretar**, no como contexto autoritativo. El XML lleva la connotación correcta de "contenido de referencia que debes consultar".

## 4.3 Orden: *lost in the middle* es real

> **Lost in the middle** (Liu et al., 2023) = el modelo recupera bien la información al **principio** o al **final** del contexto, pero la pierde cuando está **en el medio**. La curva de precisión tiene **forma de U** (cae hasta 20 puntos). Replicado en GPT-4, Claude y posteriores; **no es artefacto de una arquitectura**.

Implicación: con diez chunks por distancia ascendente, `rank=1` y `rank=10` reciben atención privilegiada, y los `rank=4–7` caen en la zona de penalización. Tu retrieval acierta pero el modelo degrada la mitad **por geometría del prompt**.

- **Most-relevant-first** (por defecto): chunks en orden de distancia ascendente. Con K=5–10 el efecto es modesto y los mejores ya están en posiciones privilegiadas.
- **Estrategia U-pattern** (para K=15–20): reordenar para que `rank=1` vaya al principio, `rank=2` al final, `rank=3` en segunda posición, etc.

  ```python
  def reorder_u_pattern(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
      front, back = [], []
      for i, chunk in enumerate(chunks):
          (front if i % 2 == 0 else back).append(chunk)
      return front + list(reversed(back))
  ```

  Queda **configurable**, no activa por defecto. Se enciende si la calidad empeora notablemente al subir K.

## 4.4 Truncamiento defensivo: cortar el chunk completo

Cuando el contexto excede el presupuesto de tokens, hay que descartar. El antipatrón es **truncar por caracteres**: el último chunk queda a medias, cualquier cita a su `id` es inválida (el modelo vio media fuente) y se desperdician sus tokens. **Regla: truncar a nivel de chunk completo — si no cabe entero, no entra.**

```python
def truncate_to_token_budget(chunks, max_context_tokens, encoder):
    selected, used_tokens = [], 0
    for chunk in chunks:  # ya ordenados por relevancia
        wrapped_size = len(encoder.encode(_wrap_chunk(chunk)))
        if used_tokens + wrapped_size > max_context_tokens:
            break
        selected.append(chunk); used_tokens += wrapped_size
    return selected
```

- **`_wrap_chunk`** cuenta los tokens del chunk **ya envuelto con delimitadores y metadata** (cuestan 30–50 tokens/chunk); ignorarlos deja un *budget* optimista y recortarás tarde.
- **Dejar margen para la salida.** El budget es total (input + output). Heurística: reservar **15 % salida + 5 % overhead**. Sobre 200k, eso deja ~160k para contexto — más de lo que cualquier retrieval razonable necesita.

## 4.5 El prompt de generación: grounding y política de "no sé"

La diferencia entre un prompt mediocre y uno disciplinado está en **cuatro elementos**: restricción de fuentes, obligación de citar, política de insuficiencia, distinción evidencia/asunción.

```python
ESTIMATOR_SYSTEM_PROMPT = """You are a senior software estimation assistant...

Rules you must follow:
1. Base every estimate ONLY on the information contained in <source> blocks.
   Do not rely on general knowledge or training data to set numbers.
2. Cite every quantitative claim with the source id it comes from. E.g.
   "Backend implementation: 45 engineer-days (source 142, source 387)".
3. Never invent source ids. If no source supports a claim, surface it as an
   assumption with explicit impact level instead.
4. If the provided context is insufficient to estimate the new project,
   set confidence to "insufficient" and list what additional information
   would be needed. Do not force an estimate.
5. Distinguish evidence-backed components from assumptions you must make.

Output must conform to the provided JSON schema."""
```

- **Regla 1** — grounding con `ONLY` en mayúsculas; el contraste tipográfico es señal de énfasis que el modelo reconoce.
- **Regla 2** — fuerza la atribución: sin ella el modelo cita "a veces".
- **Regla 3** — reduce citas inventadas dando un camino explícito ("surface as assumption") para decir "no tengo evidencia".
- **Regla 4** — el contrato más importante: el modelo **puede negarse a estimar** (`confidence = "insufficient"`).
- **Regla 5** — separa lo apoyado en el corpus de lo que requiere extrapolación.

El **user prompt** combina contexto + query estructurada y **repite la instrucción crítica al final**:

```python
def build_user_prompt(context_block, structured_query) -> str:
    return f"""Historical reference projects:

{context_block}

New project to estimate:

{structured_query.model_dump_json(indent=2)}

Generate a structured estimate. Cite sources for every quantitative claim.
If the historical context does not cover this kind of project sufficiently,
return confidence="insufficient" and explain what is missing."""
```

> La repetición es deliberada: el system prompt **define** las reglas; el user prompt las **reactiva** justo antes de generar. Los modelos atienden con fuerza al **final del prompt**, y poner ahí el recordatorio mejora la tasa de respuestas honestas cuando el contexto es flojo.

## 4.6 Esquema de salida: structured output como contrato

Misma mecánica (Responses API, `text.format`, `strict: True`), pero captura toda la estimación más los metadatos de trazabilidad:

```python
class SourceCitation(BaseModel):
    source_id: int
    relevance: Literal["primary", "supporting", "tangential"]
    used_for: str

class Assumption(BaseModel):
    description: str
    impact: Literal["high", "medium", "low"]
    rationale: str

class CostComponent(BaseModel):
    name: str
    engineer_days: int
    sources: list[int]

class Estimate(BaseModel):
    total_engineer_days: int | None
    cost_breakdown: list[CostComponent]
    duration_weeks: int | None
    sources: list[SourceCitation]
    assumptions: list[Assumption]
    confidence: Literal["high", "medium", "low", "insufficient"]
    reasoning: str
    insufficient_context_explanation: str | None = Field(default=None)
```

- `total_engineer_days` y `duration_weeks` son `int | None`: con `confidence == "insufficient"` el modelo los devuelve a `None` **en lugar de inventar un número**.
- Cada `CostComponent` carga su **propia lista de `sources`** → trazabilidad fina por componente.
- `Assumption` separa "qué se asume" de "por qué" para la revisión humana.
- `insufficient_context_explanation` activa el **soft-fail simétrico** al del retriever.

## 4.7 La llamada: gpt-5 y `reasoning.effort` (no `temperature`)

```python
response = client.responses.create(
    model="gpt-5",
    input=[{"role": "system", "content": ESTIMATOR_SYSTEM_PROMPT},
           {"role": "user", "content": user_prompt}],
    text={"format": {"type": "json_schema", "name": "Estimate",
                     "schema": Estimate.model_json_schema(), "strict": True}},
    reasoning={"effort": "medium"},
)
```

- **`gpt-5` para generación** (no `gpt-5-mini` como el reformulador): sintetizar evidencia de varias fuentes y decidir cuándo no estimar es genuinamente complejo.
- **`reasoning.effort="medium"`** sustituye al antiguo `temperature`, que **ya no es válido en gpt-5** (está en *"Deprecated parameters in reasoning models"*, S1). Valores: `low` (superficial), `medium` (el razonable), `high` (más latencia/coste sin mejora medible aquí).

## 4.8 Validación post-generación: cerrar el bucle

El structured output garantiza la **forma**, pero **no la coherencia semántica** con los chunks. Tres validaciones:

1. **Citaciones** (crítica). El modelo a veces cita un `source_id` que no se recuperó:

   ```python
   def validate_citations(estimate, retrieved_chunks) -> list[int]:
       valid_ids = {c.id for c in retrieved_chunks}
       cited_ids = set(c.source_id for c in estimate.sources)
       for component in estimate.cost_breakdown:
           cited_ids.update(component.sources)
       return sorted(cited_ids - valid_ids)  # IDs inventados
   ```

   Si devuelve algo, el orquestador: **reintenta** con feedback ("your previous response cited invalid source ids: …", máximo un reintento), **degrada la confianza** (de `high` a `medium` + anota), o **rechaza** la respuesta. El programa usa la primera y cae a la tercera si el reintento falla.

2. **Coherencia de confidence.** Si `confidence == "insufficient"`, debe existir `insufficient_context_explanation` y los numéricos ser `None`. Cualquier inconsistencia ("insufficient" con números, o "high" sin citar) → respuesta malformada, se reintenta.

3. **Sanidad numérica.** Cien mil días-ingeniero o tres semanas para un B2B complejo es probablemente un fallo. Se **marca para revisión sin bloquear**: la sanidad ayuda al humano, no es un guardarraíl absoluto.

> Flujo: `LLM call → schema validation → citation validation → confidence + sanity → Estimate ready`. Los dos primeros pueden disparar un reintento con feedback.

## 4.9 Trade-offs honestos

- **Control de "creatividad".** La intuición pide bajar `temperature` a cero, pero **ya no existe en gpt-5**. El efecto equivalente se obtiene con `reasoning.effort` bajo + prompts restrictivos. Verdad operativa: con prompt bien estructurado + structured output `strict`, la variabilidad inter-llamadas ya es muy baja **sin tocar parámetros**.
- **Estricto vs flexible.** Vuelve la asimetría de errores: el prompt es severo ("ONLY", "never invent"). A veces se niega cuando un humano habría extrapolado, pero **el ahorro en alucinaciones lo compensa**. La alternativa flexible da más cobertura aparente y menos fiabilidad real. Para presupuestos, **severo es mejor que cómplice**.
- **Coste de las citaciones.** Forzar citas sube los tokens de salida **10–20 %**. Sobre miles de peticiones/mes no es despreciable, pero la trazabilidad distingue una estimación "que el sistema produjo" de una "que el sistema puede defender".

---

# PARTE 5 — La capa de datos como servicio: aislar y securizar el retriever

> **Para cualquiera:** ya tienes el flujo RAG en un proceso. Eso es un MVP. A los dos o tres meses el equipo comercial quiere **buscar proyectos similares** sin generar estimación, y de repente "buscar" y "estimar" son **dos servicios distintos** que comparten código. Tratarlos como uno solo paga peaje a largo plazo. Esta parte los separa y convierte el prototipo en un servicio operable **durante años**.

## 5.1 El problema: dos servicios lógicos distintos

El MVP tiene un endpoint (`POST /v1/estimate`) con toda la lógica detrás. Las opciones tentadoras (`?retrieval_only=true`, o duplicar a `/v1/estimate` + `/v1/retrieve`) crean problemas que no se ven hasta meses después. Tres tensiones apuntan a separar:

- **Blast radius.** Cuando la S10 introduzca reranking sobre el retriever, cualquier cambio tocaría el endpoint de estimación aunque la generación no varíe. Radio de impacto innecesario.
- **Rate limiting diferenciado.** Estimate necesita un régimen **severo** (cada llamada cuesta euros y segundos); retrieval puede ser **mucho más permisivo** (milisegundos, casi nada). Un mismo límite o estrangula al barato o desprotege al caro.
- **Granularidad de credenciales.** Dar acceso al retrieval para un script no debería dar permiso para gastar el presupuesto de LLM.

> El retriever y el generador son **dos servicios lógicos distintos que casualmente comparten codebase.** El patrón: **dos routers separados, dos contratos públicos, dos regímenes de seguridad, y un cliente que invoca desde el backend de negocio.**

## 5.2 Dos routers, dos contratos

> **APIRouter** = mecanismo de FastAPI para agrupar y montar endpoints por separado.

```
src/estimator/api/
├── main.py        ← monta ambos routers
├── security.py    ← API keys, comparación constant-time
└── routers/
    ├── retrieval.py   ← POST /v1/retrieval/search
    └── estimate.py    ← POST /v1/estimate/from-transcript
```

```python
app = FastAPI(title="Estimator AI Service", version="0.9.0")
app.include_router(retrieval.router, prefix="/v1/retrieval", tags=["retrieval"])
app.include_router(estimate.router, prefix="/v1/estimate", tags=["estimate"])
```

El router de **retrieval** expone palancas operativas y respuesta **exhaustiva**:

```python
class SearchRequest(BaseModel):
    query_text: str = Field(min_length=10, max_length=2000)
    top_k: int = Field(default=10, ge=1, le=30)
    distance_threshold: float = Field(default=0.6, ge=0.0, le=2.0)
    sectors: list[str] | None = None
    project_year_min: int | None = Field(default=None, ge=2010, le=2030)
    chunk_types: list[str] | None = None

class SearchResponse(BaseModel):
    chunks: list[SearchResponseChunk]
    low_confidence: bool
    total_candidates_considered: int
```

El router de **estimate** tiene un contrato más simple (encapsula más):

```python
class EstimateRequest(BaseModel):
    transcript: str = Field(min_length=100, max_length=50000)
    idempotency_key: str | None = Field(default=None, max_length=128)
```

> **La asimetría es deliberada.** Retrieval expone palancas (`top_k`, `threshold`, filtros) porque sus consumidores son equipos internos que ajustan el comportamiento. Estimate expone **solo el input mínimo** (la transcripción): el backend en Rails no debería saber qué `top_k` se usa internamente. Y retrieval incluye `low_confidence` y `total_candidates_considered` como campos **de primer nivel**: el consumidor sabe siempre si se encontró material.

## 5.3 API Keys y comparación *constant-time*

El consumidor es siempre **otro servicio interno** (backend de negocio o scripts), no un usuario final. Para ese patrón, **API Keys es lo correcto**: simple, sin estado, sin OAuth. Dos cambios sobre una sola clave global: **dos claves separadas** (retrieval y estimate) y comparación con `secrets.compare_digest`, no `==`.

```python
RETRIEVAL_API_KEY = os.environ["RETRIEVAL_API_KEY"]
ESTIMATE_API_KEY = os.environ["ESTIMATE_API_KEY"]

def require_retrieval_key(x_api_key: str = Header(...)) -> str:
    if not secrets.compare_digest(x_api_key, RETRIEVAL_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key
# (require_estimate_key es idéntico contra ESTIMATE_API_KEY)
```

> **Timing attack.** La comparación nativa `==` es **non-constant-time**: termina en cuanto encuentra el primer carácter distinto. Eso crea un **canal lateral medible** — midiendo cuánto tarda el `401`, un atacante infiere byte a byte cuán cerca está su clave. `compare_digest` tarda **lo mismo** independientemente de la cercanía. **Coste de la versión segura: cero** (la misma línea), así que no hay excusa para usar `==` con secretos.

**Rotación** (fuera de scope S09): las claves deben rotarse, y la rotación debe ser **graceful** — durante la ventana, dos claves válidas a la vez (`RETRIEVAL_API_KEY` y `RETRIEVAL_API_KEY_PREVIOUS`) para que el consumidor migre sin *downtime*.

## 5.4 Rate limiting diferenciado con `slowapi`

> **slowapi** = librería de rate limiting que se monta como middleware de FastAPI/Starlette.

El detalle clave: el límite se hace **por API key, no por IP**.

```python
def get_api_key(request) -> str:
    return request.headers.get("x-api-key", get_remote_address(request))

limiter = Limiter(key_func=get_api_key)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
```

> **Por qué por API key.** Si el backend comparte una IP (tras NAT o proxy), el límite por IP sería trivial de saturar y bloquearía a legítimos. Por API key, cada consumidor tiene su propio cubo de tokens.

```python
@router.post("/search")
@limiter.limit("120/minute")
def search(...): ...

@router.post("/from-transcript")
@limiter.limit("10/minute")
def estimate(...): ...
```

**Los números** son primera aproximación por costes: retrieval ~1 ms y nada de infra → 120/min es generoso; estimate 5–15 s y 0,20–1 €/tokens → 10/min = 600/hora, suficiente para un equipo comercial y **protección contra runaway costs**. El operador los calibra con uso real.

Al exceder el límite, respuesta **informativa** con `429`:

```python
def custom_rate_limit_handler(request, exc):
    return JSONResponse(status_code=429,
        content={"error": "rate_limit_exceeded", "limit": str(exc.detail),
                 "retry_after_seconds": 60},
        headers={"Retry-After": "60"})
```

> **`Retry-After`** = header HTTP estándar que los clientes bien construidos consultan; `retry_after_seconds` en el body es la versión amigable para frontends que prefieren JSON.

## 5.5 Idempotencia: peticiones duplicadas, una sola estimación

> **Idempotency key** = un UUID que el cliente genera y envía en cada petición; si llega una key ya vista, el servicio devuelve el resultado cacheado **sin volver a llamar al LLM**.

El endpoint de estimate tiene una propiedad que retrieval no: **cada llamada cuesta**. Si el backend reintenta tras un timeout, no quieres una segunda estimación (coste doble + resultado distinto por la variabilidad del LLM).

```python
def estimate_from_transcript(transcript, idempotency_key=None) -> Estimate:
    if idempotency_key:
        cached = idempotency_store.get(idempotency_key)
        if cached:
            return Estimate.model_validate_json(cached)
    structured_query = reformulate_query(transcript)
    retrieved = search_chunks(...)
    context_block = build_context_block(retrieved.chunks)
    estimate = generate_estimate(context_block, structured_query)
    if idempotency_key:
        idempotency_store.set(idempotency_key, estimate.model_dump_json(), ttl_seconds=86400)
    return estimate
```

- **TTL de 24 h:** corto y los reintentos legítimos caen fuera; largo y la caché se vuelve un repositorio implícito de estimaciones (eso va en la BBDD del backend). 24 h cubre el escenario realista.
- **Sutileza:** el cliente puede mandar la misma key con `transcript` distinta (editó y reintentó). Protección: **hashear la transcripción** y guardar el hash; si una petición posterior con la misma key trae otro hash → **`409 Conflict`**. Opcional, fuera de scope S09.

## 5.6 Logging estructurado por etapa

> **structlog** = librería de logging con salida JSON, parseable por herramientas de observabilidad (Logfire, Langfuse, Helicone — S15).

El servicio tiene cinco etapas que fallan distinto (reformulación, retrieval, ensamblado, generación, validación) y el debug exige **distinguirlas**.

```python
@contextmanager
def log_stage(stage: str, request_id: str, **context):
    start = time.perf_counter()
    log = logger.bind(stage=stage, request_id=request_id, **context)
    log.info("stage.started")
    try:
        yield log
        log.info("stage.completed", duration_ms=round((time.perf_counter()-start)*1000, 2))
    except Exception:
        log.exception("stage.failed", duration_ms=round((time.perf_counter()-start)*1000, 2))
        raise

def estimate_from_transcript(transcript, idempotency_key=None):
    request_id = str(uuid.uuid4())
    with log_stage("reformulation", request_id):
        structured_query = reformulate_query(transcript)
    with log_stage("retrieval", request_id, sectors=structured_query.sector):
        retrieved = search_chunks(...)
    with log_stage("context_assembly", request_id, chunks=len(retrieved.chunks)):
        context_block = build_context_block(retrieved.chunks)
    with log_stage("generation", request_id, confidence_target="adaptive"):
        estimate = generate_estimate(context_block, structured_query)
    with log_stage("validation", request_id):
        validate_estimate(estimate, retrieved.chunks)
    return estimate
```

- **`request_id`** ata todas las líneas de una petición en una traza; sin él, los logs de cinco etapas se entremezclan con peticiones concurrentes. Se incluye como header **`X-Request-ID`** en la respuesta, para que el backend correlacione.
- **Dos atributos por etapa siempre:** `duration_ms` (detectar regresiones de latencia) + un campo de debug específico (`sectors`, `chunks`, `confidence`). Son los que, meses después, permiten reconstruir la cadena de decisiones **sin reproducir la petición**.

## 5.7 El cliente Ruby desde el backend de negocio

El patrón es independiente del stack; se muestra en Ruby por alineación con la implementación de referencia (Rails + Faraday):

```ruby
class EstimatorClient
  ESTIMATE_TIMEOUT = 30  # seconds
  RETRY_OPTIONS = { max: 2, interval: 1.5, backoff_factor: 2,
                    retry_statuses: [502, 503, 504], methods: [:post] }.freeze

  def initialize(base_url:, api_key:)
    @conn = Faraday.new(url: base_url) do |f|
      f.request :json
      f.request :retry, RETRY_OPTIONS
      f.options.timeout = ESTIMATE_TIMEOUT
      f.options.open_timeout = 5
      f.headers["X-API-Key"] = api_key
    end
  end

  def estimate_from_transcript(transcript:, idempotency_key: SecureRandom.uuid)
    response = @conn.post("/v1/estimate/from-transcript") do |req|
      req.body = { transcript: transcript, idempotency_key: idempotency_key }
    end
    raise EstimationError, response.body["detail"] if response.status >= 400
    response.body
  end
end
```

- **Timeouts diferenciados:** `open_timeout` 5 s (detectar rápido que el servicio cayó) y `timeout` 30 s (cubrir el peor caso de LLM con `reasoning.effort` alto). Sin ellos, Faraday cae a 60 s para todo.
- **Retry solo `5xx`** (`502/503/504`, transitorio): reintentar un `400`/`401` no tiene sentido; un `500` puro es ambiguo.
- **`idempotency_key` por defecto** con `SecureRandom.uuid`: si el retry se activa, la **misma key** viaja y la idempotencia funciona **automáticamente**.

## 5.8 Trade-offs honestos

- **API Key vs JWT vs mTLS.** API Key tiene dos límites: no lleva identidad más allá de "alguien con esta clave", y si se filtra cualquiera la usa hasta rotarla. JWT mitiga la primera (lleva *claims*), no la segunda; mTLS mitiga ambas a costa de complejidad operativa (certificados, CA). Para un servicio interno con un único consumidor en infra controlada, **API Key es el mejor coste/beneficio**. Con múltiples consumidores externos → JWT; con *service mesh* (Istio, Linkerd) → mTLS casi gratis. **Depende del contexto, no de una preferencia universal.**
- **OWASP API Security Top 10** es la lectura complementaria; lo importante es el reflejo de **revisar la lista cada vez que se añade un endpoint**.
- **Rate limiting in-memory vs distribuido.** `slowapi` usa memoria del proceso por defecto. Con **múltiples workers** (gunicorn `-w 4`) o varias instancias, cada uno lleva su cuenta y el límite efectivo **se multiplica por workers**. Aceptable para el MVP; S15 mete Redis al escalar horizontalmente. **El cambio es de configuración, no de código** (`slowapi` soporta Redis nativo).

---

# Chuleta de una página

- **CAG → RAG:** CAG congela el contexto en el prompt; RAG lo **busca cada vez**. Cuatro etapas: **Query → Retrieval → Augmentation → Generation** (Lewis et al., 2020). RAG gana en frescura, techo de corpus, trazabilidad y resistencia a alucinación; **pierde** en latencia/coste (3–4 llamadas). CAG sigue correcto para corpus pequeños y estables (Chan et al., 2024).
- **El mantra:** *"no prompt fixes bad retrieval"*. El **retrieval fija el techo**. Debug: ¿chunks correctos? → ¿contexto bien montado? → ¿prompt fuerza grounding? → ¿modelo capaz? (en ese orden).
- **Query (reformulación):** embeber la transcripción cruda falla (longitud disuelve la señal, ruido ahoga keywords, anáforas contaminan). Cinco familias: rewriting, sub-query+RRF, step-back, HyDE, **extracción estructurada** (la elección: JSON Pydantic `strict` → texto compuesto **+ filtros de metadata**; única con artefacto inspectable y utilidad downstream). Fallback a rewriting; alarma si se activa >5 %.
- **Retrieval:** `top_k` **moderado y estable** (~10); **no subir K** para arreglar calidad. **Threshold** ≈ valle de la distribución empírica (0.6–0.65 para `text-embedding-3-small`); 0 resultados = info válida → **soft-fail** (`low_confidence`, no llamar al generador con contexto vacío). Filtros: **pre / post / in-query**; con pgvector ≥0.7 e *iterative scans*, lo escribes como pre y el **planner decide**. Operador de query ↔ operator class (`<=>` ↔ `vector_cosine_ops`) o cae a *seq scan*.
- **Recall vs precision:** producción con consecuencias económicas → **prioriza precision**. Asimetría: una alucinación con número es peor que un "no lo sé" honesto.
- **Augmentation:** `"\n\n".join` produce citas inventadas, mezclas y respuestas sin contexto. Delimitadores **`<source id=... distance=...>`** (XML > JSON; metadata como atributos). Orden: **lost in the middle** (curva en U, Liu et al. 2023) → most-relevant-first por defecto, U-pattern si K≥15. Truncar a **chunk completo** contando wrappers; reservar **15 % salida + 5 % overhead**.
- **Generation:** prompt con **grounding** ("ONLY"), **obligación de citar**, **política de insuficiencia** (`confidence="insufficient"`, no forzar), evidencia vs asunción; repetir lo crítico al **final**. `gpt-5` + **`reasoning.effort`** (`temperature` muerto en gpt-5). Structured output `strict` como contrato. **Validar post-generación:** citaciones (sin `source_id` fabricados → reintento), coherencia de confidence, sanidad numérica.
- **Capa de datos como servicio:** retriever y generador = **dos servicios distintos**. Dos `APIRouter` (`/v1/retrieval/search` con palancas; `/v1/estimate/from-transcript` con input mínimo). **Dos API keys** + `secrets.compare_digest` (no `==`, *timing attack*). **Rate limit por API key** (no IP) y diferenciado (120/min vs 10/min) + `429` con `Retry-After`. **Idempotencia** (`idempotency_key`, TTL 24 h, hash de transcript → `409`). **Logging** `structlog` por etapa con `request_id`/`X-Request-ID` + `duration_ms`. Cliente con timeouts diferenciados + retry solo `5xx` + key por defecto. **API Key** = mejor coste/beneficio para servicio interno (JWT/mTLS según contexto).

---

## Cómo conecta con nuestro ejercicio y con el directo

El **ejercicio pre-sesión** es correr la transcripción ambigua sobre el CAG actual e identificar **cinco fallos**, que mapean a las cuatro etapas: query cruda no recupera (Query), chunks irrelevantes o mezclados (Retrieval), concatenación naive da respuestas pobres (Augmentation), el modelo inventa o no cita (Generation). Llegar con esa correspondencia mental hecha es lo que más valor aporta.

La **sesión en vivo** son seis bloques:

1. **CAG vs RAG en paralelo:** misma transcripción ambigua por el CAG de la S5 y un esqueleto RAG, midiendo respuesta, latencia, coste y trazabilidad.
2. **Iterar la reformulación:** contrastar tres caminos — embedding crudo (baseline), extracción estructurada, HyDE — midiendo cuántos chunks pertenecen al sector y geografía correctos.
3. **Decisiones del reformulador:** ¿inferir tecnologías no mencionadas? ¿`sector = null` ante ambigüedad? ¿`scale="pilot"` de "dos clínicas piloto"?
4. **Parámetros del retriever:** variar `top_k` (3–30), `threshold` (0.5–0.8) y filtros, midiendo nº de chunks, % del sector correcto y latencia mediana. El objetivo **no es encontrar los parámetros "óptimos"** (es folklore) sino **interiorizar la sensibilidad** a cada palanca.
5. **El prompt de generación:** partir del prompt mínimo (raw) y añadir restricciones de una en una. Más una **demo de *lost in the middle*** moviendo el chunk crítico de posición.
6. **Cierre end-to-end y seguridad:** rate limit absurdo (2/min), tres peticiones desde el cliente Ruby, observar `429` + `Retry-After` + el efecto del `idempotency_key`. Más un escenario de seguridad: **filtrar una API key en un commit** y discutir la respuesta (rotación inmediata, deploy de la nueva, por qué dos claves separadas limitan el daño).

> **El cierre conceptual de la S9:** lo que has construido ya no es un script con un LLM detrás, es un **servicio operable** — contratos claros, autenticación diferenciada, rate limits, idempotencia, logging y un cliente robusto. La S10 evolucionará el retrieval (reranking, híbrida) tocando **un solo módulo** sin que estimate, rate limit, credenciales o cliente Ruby cambien. **El aislamiento es lo que hace esa evolución posible.**
