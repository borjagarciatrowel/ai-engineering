# Sesión 9 — Teoría: del CAG estático al flujo RAG (query · retrieval · augmentation · generation) y la capa de datos como servicio

> Este documento resume **los cinco artículos teóricos** de la Sesión 9 en un único texto, en
> orden:
>
> 1. **Del CAG estático al flujo RAG:** las cuatro etapas canónicas y por qué el retrieval domina.
> 2. **Reformulación de queries:** convertir una transcripción ruidosa en algo que el retriever pueda usar.
> 3. **Retrieval que no es solo coseno:** top-K, threshold y filtros de metadata sobre pgvector.
> 4. **Augmentation y generación:** ensamblar el contexto y forzar *grounding* para que el LLM no alucine.
> 5. **La capa de datos como servicio:** aislar y securizar el retriever (dos routers, auth, rate limiting, idempotencia, logging).
>
> Cada parte empieza, cuando hace falta, con una **explicación para cualquiera** (sin tecnicismos)
> y luego entra en el detalle técnico. Al final hay una **chuleta de una página** con lo
> imprescindible. La Sesión 9 es la primera del módulo de RAG; las Sesiones 10 (reranking y
> búsqueda híbrida) y 11 (evaluación) continúan refinando la etapa de retrieval.

---

## 0. La idea en una página (para cualquiera)

Hasta ahora el sistema de estimaciones funcionaba con un truco sencillo llamado **CAG**
(*Cache-Augmented Generation*): metíamos ~30 presupuestos históricos **dentro del prompt** del
modelo, de una vez y para siempre, y le pedíamos que estimara apoyándose en ellos. Funciona
mientras el cliente pida algo parecido a esos 30 ejemplos. En cuanto menciona algo nuevo —"un
marketplace sanitario en Alemania con KYC reforzado por la BaFin"— el modelo no tiene referencias y
**se inventa un número**. Y si la empresa cierra cinco proyectos nuevos esta semana, el sistema no
se entera hasta que alguien reescriba el prompt y vuelva a desplegar. El conocimiento está
**congelado**.

**RAG** (*Retrieval-Augmented Generation*) cambia la pregunta de fondo. En lugar de "¿qué
presupuestos meto en el prompt para que el modelo siempre tenga referencias?", pasa a ser "¿cómo
**busco**, en el momento de cada petición, los presupuestos más relevantes y se los doy al modelo?".
Una analogía: CAG es estudiar para un examen memorizando 30 fichas y rezar para que las preguntas
caigan ahí; RAG es ir al examen con acceso a la biblioteca entera y saber **buscar** la ficha justa
para cada pregunta.

Ese "buscar cada vez" se descompone en **cuatro etapas encadenadas**, la nomenclatura que fijó el
paper de Lewis et al. (2020) y que ha aguantado sin cambios pese a todas las variantes modernas
(Agentic RAG, GraphRAG, Self-RAG…):

1. **Query** — convertir la entrada del usuario en algo buscable.
2. **Retrieval** — encontrar los fragmentos (*chunks*) relevantes en la base vectorial.
3. **Augmentation** — ensamblar esos chunks en un bloque de contexto que el modelo entienda bien.
4. **Generation** — llamar al LLM con ese contexto y un prompt que le obligue a usarlo.

La **primera lección operativa** del módulo, y la que conviene grabar antes de seguir, es un mantra
de la industria: *"no amount of prompt engineering fixes bad retrieval"* — **ningún prompt arregla
un mal retrieval**. El techo de calidad de todo el sistema lo fija la etapa de Retrieval; las otras
tres pueden acercarte a ese techo, pero nunca por encima de él. Por eso este módulo dedica casi todo
su esfuerzo a esa etapa.

RAG no es "mejor" que CAG en abstracto: es **distinto** y resuelve problemas distintos, a cambio de
más complejidad, más latencia y más coste por petición. El resto del documento desmonta las cuatro
etapas, explica qué decisiones de diseño esconde cada una, y termina convirtiendo el prototipo en un
**servicio operable** que el equipo pueda mantener durante años.

---

# PARTE 1 — Del CAG estático al flujo RAG

## 1.1 El techo del CAG

El sistema cerrado en la Sesión 5 producía estimaciones decentes **mientras la transcripción
describiera proyectos parecidos** a los presupuestos que metiste en el *system prompt*. Su techo
tiene dos caras:

- **Conocimiento congelado.** Añadir un presupuesto nuevo exige editar el prompt y redesplegar. El
  sistema envejece con el tiempo.
- **Límite de contexto.** Si tienes 800 presupuestos × ~3.000 tokens = 2,4 M tokens, no caben en
  ninguna ventana de contexto. Los 770 que no metiste están **fuera del alcance del modelo para
  siempre**.

Ante algo no cubierto, el modelo hace una de dos cosas, ambas inaceptables para un estimador serio:
inventa apoyándose en su conocimiento paramétrico genérico, o produce un número razonable **sin
fundamento real en datos de la empresa**.

## 1.2 La anatomía del flujo RAG: cuatro etapas, cuatro puntos de fallo

Cada etapa hace **trabajo real** y es un punto donde la calidad puede degradarse:

- **Query.** No es trivial. En un RAG de manual "la query" es la pregunta tal cual. Aquí la entrada
  es una transcripción de miles de tokens con ruido conversacional, divagaciones y anáforas.
  Embeberla directa y compararla con chunks de 300 tokens produce un vector "promediado" que apenas
  discrimina. La etapa Query extrae los requisitos clave y genera consultas optimizadas
  (→ **Parte 2**).
- **Retrieval.** Recibe queries optimizadas y devuelve los chunks más relevantes. La versión naive
  (top-K por coseno, sin filtros ni umbral) que dejaste en la Sesión 8 se queda corta. En producción
  el retrieval combina similitud vectorial + filtros estructurales + umbrales, y más adelante
  *reranking* (Sesión 10). **Es la etapa de mayor impacto** (→ **Parte 3**).
- **Augmentation.** Ensambla los chunks en un bloque de contexto. El reflejo ingenuo —concatenar con
  un separador— es exactamente lo que produce alucinaciones y citas inventadas. Bien hecha decide
  orden (mitigando *lost in the middle*), delimitadores, truncamiento y metadata para citación
  (→ **Parte 4**).
- **Generation.** La llamada al LLM con el contexto ya montado y un prompt que fuerza *grounding*
  ("usa solo el contexto"), define el comportamiento ante contexto insuficiente, fija el formato de
  salida y permite validar citaciones (→ **Parte 4**).

En código, el orquestador del flujo son **cinco líneas operativas**, y cada una es una decisión de
diseño y una fuente potencial de degradación:

```python
async def estimate_from_transcript(transcript: str) -> EstimateResponse:
    structured_query = await query_reformulator.reformulate(transcript)
    chunks = await retriever.search(
        query=structured_query,
        top_k=10,
        threshold=0.65,
        filters=structured_query.metadata_filters,
    )
    context = context_assembler.assemble(chunks, max_tokens=4000)
    estimate = await generator.generate(
        transcript=transcript,
        context=context,
        schema=EstimateSchema,
    )
    return estimate
```

**Impacto en la estructura del servicio IA.** El pipeline introduce dos carpetas nuevas respecto al
cierre de la Sesión 8, sin tocar las existentes:

```
Cierre Sesión 08          Cierre Sesión 09
  ingest/          (S06)    ingest/
  embedding_pipeline/ (S07) embedding_pipeline/
  storage/         (S08)    storage/
                            retrieval/    ← query_reformulator.py, retriever.py
                            generation/   ← context_assembler.py, prompt_builder.py, estimator.py
```

`ingest/`, `embedding_pipeline/` y `storage/` quedan como **dependencias estables**. Esa separación
no es estética: permite que el retriever evolucione en la Sesión 10 (reranking) sin tocar la
generación, y al revés.

## 1.3 CAG vs RAG: las cinco diferencias operativas que importan

El contraste no es solo "tamaño de contexto". Son cinco diferencias medibles:

1. **Frescura del conocimiento.** CAG: editar prompt + validar caché + redesplegar. RAG: un
   `POST /v1/retrieval/insert` que el backend llama al cerrar una venta. Sincronizado en minutos sin
   tocar código. **Esta diferencia justifica RAG por sí sola** en cualquier empresa que cierre
   proyectos con regularidad.
2. **Techo del corpus.** CAG está limitado por la ventana del modelo (~400k con gpt-5). RAG no tiene
   techo: el corpus crece tanto como quieras y solo subes los chunks relevantes. **Escala con tu
   empresa, no con el modelo.**
3. **Latencia y coste por petición.** Aquí **RAG pierde**, y conviene reconocerlo. CAG = 1 llamada
   con prompt estático que aprovecha *prompt caching* agresivo (1–2 s, barato). RAG = reformulación
   + embeddings + consulta a pgvector + generación; la latencia se acumula y el coste puede ser 3–4×
   el de CAG. Si el volumen es alto y el corpus estable, no es trivial.
4. **Trazabilidad y auditoría.** CAG: no puedes explicar de dónde salió un número (mezcla difusa de
   prompt + conocimiento paramétrico). RAG: "estos son los presupuestos que se recuperaron, este el
   contexto, esta la estimación". Decisivo ante auditorías, clientes exigentes o regulación.
5. **Resistencia a la alucinación.** CAG no fuerza al modelo a apoyarse en los datos del prompt. RAG,
   con un prompt de generación bien construido ("usa solo el contexto, cita las fuentes, declara
   cuando la evidencia sea insuficiente"), **reduce de forma medible y reproducible** la tasa de
   alucinación. No la elimina.

| Dimensión | CAG | RAG |
|---|---|---|
| Frescura | Estática, *redeploy* | Incremental, en vivo |
| Techo del corpus | ~400k tokens | Ilimitado |
| Latencia y coste | 1 llamada, bajo | 3–4 llamadas, medio |
| Trazabilidad | Difusa | Precisa, citable |
| Resistencia a alucinación | Baja | Alta con *grounding* |

> La idea que resume las cinco: **CAG asume que el contexto correcto está siempre disponible porque
> lo elegiste por adelantado; RAG asume que hay que ir a buscarlo cada vez y que esa búsqueda es el
> corazón del sistema.** Más robusto a la realidad, pero pone más complejidad en la arquitectura. No
> hay almuerzo gratis.

## 1.4 Cuándo CAG sigue siendo la respuesta correcta

RAG **no es universalmente mejor**. El paper *"Don't Do RAG: When Cache-Augmented Generation is All
You Need for Knowledge Tasks"* (Chan et al., 2024) demostró que **con corpus pequeño y estable, CAG
no solo es más simple sino que produce mejores respuestas** en métricas estándar de QA. La intuición:
en CAG el modelo "ve" todo el corpus en una sola atención completa; en RAG ve un subconjunto elegido
por un retriever **que puede equivocarse**. Cuando el coste del error del retriever es alto y el
corpus cabe en contexto, CAG gana.

CAG es perfectamente respetable para **corpus < ~100k tokens efectivos, estables**, donde el coste
por petición importa y la trazabilidad no es crítica: FAQs internas, asistentes sobre documentación
de producto que cambia poco, herramientas legales sobre un cuerpo normativo fijo.

Existe una **tercera vía híbrida**: contexto base estable (políticas, terminología, plantillas JSON,
reglas de coherencia) por **CAG** en el system prompt, y contexto variable (presupuestos similares)
por **RAG**. Es el siguiente paso natural de optimización, pero la complejidad añadida no se
justifica para el alcance del programa.

Para el proyecto, RAG está justificado porque el corpus de presupuestos **crece con el tiempo y no
cabe completo en contexto**.

## 1.5 El retrieval domina

> *"No amount of prompt engineering fixes bad retrieval."*

No es un eslogan bonito: describe **el modo de fallo más común en RAG en producción**. La intuición:
si el retrieval devuelve los chunks correctos, incluso un prompt mediocre produce respuestas
decentes (el modelo tiene la evidencia delante). Si devuelve chunks irrelevantes, **ningún prompt te
salva**: el modelo no puede inventar evidencia que no tiene, y si lo obligas a apoyarse solo en el
contexto, responderá "no tengo suficiente información".

De ahí el **orden de prioridades cuando un RAG falla**, siempre el mismo:

1. ¿Estoy recuperando los chunks correctos? Si no, todo lo demás es ruido.
2. ¿Estoy ensamblando bien el contexto? (Si los chunks llegan pero el modelo los ignora → Augmentation.)
3. ¿El prompt fuerza *grounding*?
4. **Solo en último lugar:** ¿el modelo es suficientemente capaz?

La tentación de empezar por el modelo es fuerte y **casi siempre equivocada**. La ingeniería de
retrieval es donde está el palanqueo.

---

# PARTE 2 — Reformulación de queries

> **Para cualquiera:** la primera tentación al recibir una transcripción real es embeberla tal cual
> y pasársela al buscador. No funciona, y no por magia matemática: es algo mundano. Una transcripción
> es ruido conversacional con las palabras importantes enterradas. Hay que **destilarla** antes de
> buscar. Esa capa de destilado se llama *reformulación de queries* y es lo que más impacta en el
> *recall* del sistema.

## 2.1 Por qué embeber la transcripción cruda falla

Tres cosas rompen la búsqueda vectorial cuando metes una transcripción entera:

1. **La longitud disuelve la señal.** Tus chunks son de ~300 tokens, cada uno sobre un componente
   concreto; su vector apunta a una región muy específica del espacio. Si embebes 2.000 tokens con
   cinco temas mezclados, el vector resultante es el **centroide de cinco regiones**: un punto "en
   medio de todas y cerca de ninguna". Las distancias coseno se comprimen alrededor de un valor medio
   mediocre y el sistema no distingue lo crítico de lo periférico.
2. **El ruido conversacional ahoga las keywords técnicas.** Las palabras que discriminan
   ("marketplace", "Stripe Connect", "KYC", "BaFin", "SAP", "salud", "piloto") quedan enterradas
   entre conectores y coloquialismos ("pues mira", "lo nuestro", "no es un Amazon"). El embedder no
   sabe que esas siete palabras son las que importan.
3. **Las anáforas no significan nada para el embedder.** "Lo que hablábamos el otro día", "lo
   nuestro", "como me decíais" se apoyan en contexto que no está en la transcripción. El embedder las
   codifica como contenido informativo, **contaminando el vector con señal que no remite a nada**.

Conclusión: necesitas una capa que convierta la transcripción en algo que el retriever pueda usar.
**Sin ella, ningún ajuste de top-K, threshold o reranker te salva** de la entrada degradada.

## 2.2 Las cinco familias de reformulación

| Técnica | Coste | Recall | ¿Produce filtros? |
|---|---|---|---|
| Query rewriting | Bajo | Bajo a medio | No |
| Sub-query decomposition | Alto | Alto pero ruidoso | No |
| Step-back prompting | Bajo | Variable | No |
| HyDE | Medio | Alto | No |
| **Extracción estructurada** | Medio | Alto | **Sí** |

- **Query rewriting.** La más simple: pides al LLM que reformule la entrada como "una consulta
  técnica concisa". Funciona con entradas cortas mal formuladas; falla con entradas largas multi-tema
  porque pierdes información en la compresión arbitraria.
- **Sub-query decomposition.** El LLM descompone la entrada en varias sub-queries (una por sub-tema),
  cada una se busca independientemente y los resultados se fusionan (típicamente con **Reciprocal
  Rank Fusion**). Mejora el recall pero multiplica el coste (N búsquedas + N embeddings) y añade la
  complejidad de fusionar resultados contradictorios.
- **Step-back prompting.** Sube un nivel de abstracción antes de buscar (de lo específico a "qué tipo
  de proyectos…"). Brilla en QA sobre conocimiento estructurado (Wikipedia, textos técnicos) y rinde
  peor en dominios *narrow* como estimación de software, donde el "concepto general" es difuso. Apenas
  se toca en el programa.
- **HyDE (*Hypothetical Document Embeddings*).** Invierte el problema: en lugar de embeber la
  pregunta, pide al LLM una **respuesta hipotética** —un documento ficticio que se parecería a la
  respuesta correcta— y embebe eso. El insight: tu base contiene documentos descriptivos, y un
  documento sintético se parece más a otros documentos que una pregunta corta. Funciona muy bien
  cuando el dominio es estable y conocido por el modelo; **peor cuando el modelo alucina tecnologías
  que tu empresa nunca ha usado**.
- **Extracción estructurada** (la elección del programa, ver 2.3).

## 2.3 La elección del programa: extracción estructurada

En lugar de pedir texto reformulado o un documento sintético, pides un **objeto estructurado**: un
JSON validable contra un esquema explícito. Para la transcripción de ejemplo:

```python
from pydantic import BaseModel, Field
from typing import Literal

class EstimationQuery(BaseModel):
    function: str = Field(description="Primary product function in 3-8 words")
    technologies: list[str] = Field(default_factory=list,
        description="Specific technologies, services, or integrations mentioned")
    sector: str | None = Field(default=None,
        description="Industry or vertical if explicitly mentioned")
    scale: Literal["pilot", "small", "medium", "large"] | None = Field(default=None,
        description="Project scale if inferable from the conversation")
    country: str | None = Field(default=None, description="Geographic scope if mentioned")
    regulations: list[str] = Field(default_factory=list,
        description="Regulatory frameworks mentioned (GDPR, BaFin, HIPAA...)")
    constraints: list[str] = Field(default_factory=list,
        description="Non-negotiable requirements or hard constraints")
```

La llamada usa la **Responses API** de OpenAI con `text.format` de tipo `json_schema` y `strict:
True` para que el modelo no se desvíe del esquema:

```python
async def reformulate(transcript: str) -> EstimationQuery:
    response = await client.responses.create(
        model="gpt-5-mini",
        input=[
            {"role": "system", "content": REFORMULATION_SYSTEM_PROMPT},
            {"role": "user", "content": transcript},
        ],
        text={"format": {
            "type": "json_schema", "name": "EstimationQuery",
            "schema": EstimationQuery.model_json_schema(), "strict": True,
        }},
    )
    return EstimationQuery.model_validate_json(response.output_text)
```

El system prompt instruye a extraer **solo lo explícitamente mencionado o inequívocamente inferible**
y dejar campos opcionales en `null`. La tentación de "rellenar con sentido común" (inferir GDPR
porque hay datos personales, Stripe porque hay pagos) es la **principal fuente de errores en
producción** y conviene reprimirla en el prompt.

Ese objeto se usa de **dos maneras** —y aquí está su ventaja sobre las otras cuatro técnicas, que no
producen estructura aprovechable—:

1. **Sus campos textuales se componen en un texto sintético** que se embebe (similar a HyDE pero más
   controlado):

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
   #    for the healthcare sector. in Germany. compliant with BaFin. requiring SAP reconciliation."
   ```

2. **Sus campos categóricos se usan como filtros de metadata en pgvector** (`sector = "healthcare"`,
   etc.). Información que **se pierde en cualquier otra técnica**.

El vector de ese texto compuesto vive cerca de los chunks de presupuestos fintech B2B para sectores
regulados, no en el centroide difuso de la reunión. La mejora en recall sobre la misma base es
**típicamente entre 2× y 5×**.

**Por qué se elige (no por ser la más sofisticada):** HyDE da vectores ligeramente mejores en
benchmarks puros, pero extracción estructurada ofrece el mejor balance entre cuatro dimensiones de
producción: **predictibilidad de coste** (JSON de 50–100 tokens vs 200–400 de HyDE),
**predictibilidad de latencia** (una sola llamada), **debugabilidad** (es la única que produce un
artefacto inspectable: puedes mirar el JSON y ver si confundió el sector o interpretó "piloto" como
"small") y **utilidad downstream** (alimenta los filtros de metadata).

**Patrón de fallback.** Si la validación del JSON falla (el modelo produjo algo fuera de esquema, o
la transcripción es genuinamente ambigua), el sistema cae a **query rewriting puro**: un texto
reformulado libre. Peor que extracción, mejor que la transcripción cruda. **El fallback debe
activarse y registrarse** para iterar: si nunca se activa, el reformulador es demasiado tolerante; si
se activa **más del 5 %**, hay un problema sistemático con el prompt o el esquema.

## 2.4 Trade-offs honestos: cuándo subir a algo más sofisticado

La decisión por defecto no es universal:

- **Subir a HyDE** tiene sentido cuando el corpus es muy descriptivo (chunks de prosa elaborada) y el
  modelo conoce bien el dominio (documentación médica o jurídica). Para chunks semi-formales de
  componentes presupuestarios, el beneficio es **marginal**.
- **Subir a sub-query decomposition** tiene sentido cuando las transcripciones son
  consistentemente multi-tema y los temas **ortogonales**. Para el patrón típico (un cliente describe
  un proyecto con varias dimensiones), la extracción captura esas dimensiones en campos del JSON y
  rinde mejor que descomponer.
- **Subir a una técnica híbrida** (extracción para filtrar + HyDE para la búsqueda semántica, las dos
  en paralelo) es la trayectoria razonable de evolución si el recall se queda corto tras semanas de
  uso. No la elección inicial.

> **Lo que no compensa** es complicar el reformulador **antes de medir**. Empezar por HyDE "porque
> suena mejor en los papers" lleva al mismo sitio que empezar por un reranker: sistemas complejos,
> difíciles de depurar, con mejoras marginales que ni siquiera son medibles porque no había una
> *baseline* simple contra la que comparar. Regla del módulo: **construir la versión más simple,
> instrumentarla, medir sobre transcripciones reales, y solo entonces decidir** si la complejidad se
> justifica.

La reformulación **no es un detalle del retriever**: es una capa con vida propia que merece su prompt
versionado, su esquema versionado, su instrumentación y su *test suite*. La mayoría de las regresiones
de calidad en producción vendrán del momento en que alguien edita el prompt para arreglar un caso y
rompe diez que iban bien sin darse cuenta. Esa fragilidad es la contrapartida de poner un LLM en la
entrada del sistema.

---

# PARTE 3 — Retrieval que no es solo coseno: top-K, threshold y filtros

> **Para cualquiera:** la búsqueda por similitud que montaste en la Sesión 8 pide "los K chunks más
> parecidos" y ya. En el mundo real eso produce dos sorpresas desagradables. Esta parte añade dos
> disciplinas —un **umbral de calidad** (no metas basura aunque te falten resultados) y **filtros
> estructurales** (no mezcles peras con manzanas)— usando operadores que pgvector ya te ofrece.

## 3.1 Las dos sorpresas del retrieval naive

Al pasar la salida del reformulador sobre una transcripción real, aparece una de dos:

- **Resultados clónicos.** Pides 10 chunks; 8 pertenecen al **mismo** presupuesto histórico. Solo
  había un proyecto realmente similar, y como `top-K=10` exige diez resultados, el resto se rellena
  con chunks del mismo proyecto. Tu estimación está fundada en **un solo caso, no en diez**.
- **Resultados mediocres.** El corpus no tiene presupuestos genuinamente similares. El retriever
  devuelve diez, pero todas las distancias están comprimidas en torno a **0.7–0.8**: ninguno es
  realmente parecido. Cumple la promesa literal ("los diez más similares") pero la estimación será
  una **alucinación apoyada en presupuestos genéricamente parecidos**.

Causa común: el retriever usa **una sola palanca** (`top-K`) y le faltan dos disciplinas: **calidad
mínima** (un umbral por debajo del cual nada entra) y **filtrado estructural** (no todo chunk es
candidato para toda query).

## 3.2 Top-K: la palanca obvia y sus tres sesgos

`top-K` define cuántos chunks devuelve el retriever, ordenados por distancia ascendente. El reflejo
al ver resultados pobres es **subir K**. A veces funciona (en corpus grandes con queries ambiguas,
rescata chunks relevantes "más abajo en la cola"), pero por reflejo trae tres consecuencias con coste
medible:

1. **El coste del prompt de generación se multiplica casi linealmente con K.** Cada chunk son 200–400
   tokens; pasar de K=10 a K=30 añade 4.000–8.000 tokens al prompt. Si una generación con gpt-5
   cuesta ~0,50 € con K=10, con K=30 cuesta ~1,50 €. Multiplícalo por miles de peticiones/mes.
2. **El ruido degrada la calidad, no la mejora.** Por el fenómeno *lost in the middle* (→ Parte 4),
   meter 30 chunks parcialmente relevantes hace que el modelo ignore la mayoría. El chunk crítico en
   posición 14 recibe menos atención que el irrelevante en posición 1.
3. **Subir K oculta el problema real.** Si solo hay 3 chunks realmente similares y pides 10, no haces
   mejor retrieval: haces el mismo retrieval **con 7 distracciones**. El sistema te está diciendo "no
   hay más material relevante" y la respuesta correcta es **propagar esa señal**, no disfrazarla.

> **Regla del programa:** mantener `K` en un valor **moderado y estable** (10 es razonable) y dejar
> que el **threshold** descarte lo que no merece entrar. El número de chunks por petición no es fijo:
> es un **emergente** del threshold aplicado sobre los K candidatos —a veces 10, a veces 3, a veces
> **0**. Y cero es información válida, no un fallo.

## 3.3 Threshold: la disciplina que falta

El threshold decide qué distancia es **lo bastante baja** para que un chunk merezca entrar. En
pgvector, donde `<=>` produce distancia coseno entre 0 (idénticos) y 2 (opuestos), un umbral típico
para embeddings de OpenAI está entre **0.5 y 0.7**: por debajo, el chunk es razonablemente similar;
por encima, es contenido tangencial que confundirá más que ayuda.

**El número exacto no se decide por intuición, se decide mirando la distribución empírica de
distancias.** El procedimiento: coges 20–30 transcripciones representativas, las pasas por el
reformulador, ejecutas con `K=50` **sin threshold**, y graficas las distancias. Verás dos grupos: un
grupo pequeño de distancias bajas (≈0.3–0.5) que a inspección manual son **relevantes**, y un grupo
grande en torno a **0.7–0.9** que es **ruido**. El threshold se coloca en el **valle entre los dos
grupos**; para `text-embedding-3-small` sobre un corpus razonablemente especializado, ese valle suele
caer alrededor de **0.6–0.65**.

Una vez fijado, se aplica como un `WHERE` adicional a la SQL que ya tenías:

```sql
SELECT c.id, c.content, c.metadata,
       c.embedding <=> :query_embedding AS distance
FROM chunks c
WHERE c.embedding <=> :query_embedding < :distance_threshold
ORDER BY c.embedding <=> :query_embedding
LIMIT :top_k;
```

> **Detalle operativo:** el `WHERE` y el `ORDER BY` evalúan la misma distancia. El planner de Postgres
> la reutiliza **solo si el índice HNSW está bien configurado con la operator class alineada con el
> operador de la query** (`vector_cosine_ops` ↔ `<=>`). Si la operator class fuera `vector_l2_ops` y
> la query usa `<=>`, el índice **no se aplica**, cae a *sequential scan* y la búsqueda pasa de
> milisegundos a segundos. Es el antipatrón silencioso de la Sesión 8, y la condición previa para que
> cualquier ajuste de threshold tenga el comportamiento esperado.

**Comportamiento cuando ningún chunk supera el threshold: soft-fail.** El endpoint devuelve una
**lista vacía** y un campo `low_confidence: true`. El orquestador, al ver la lista vacía, **no llama
al generador con contexto vacío** (eso solo invita a alucinar): produce una respuesta directa del
tipo *"no hay evidencia suficiente en el corpus histórico para estimar este proyecto; revisar
manualmente"*. Esta semántica —**el sistema reconoce sus límites y los comunica hacia arriba**— es lo
que distingue un RAG serio de uno didáctico.

Una alternativa es **relajar el threshold dinámicamente**: empezar estricto (`0.55`), y si devuelve
menos de 3 chunks, relajar a `0.65` y repetir. Mejora válida, pero introduce no-determinismo y
dificulta el debug; el programa no la adopta por defecto.

## 3.4 Filtros de metadata: tres estrategias en pgvector

La similitud vectorial captura semejanza semántica pero **ignora datos estructurales** que pueden ser
críticos: si la transcripción habla de sector salud, no quieres chunks de retail aunque sean
semánticamente cercanos; si el proyecto es para el año que viene, no quieres anclarlo en presupuestos
de 2019 con tecnologías obsoletas. Los filtros estructurales añaden cláusulas `WHERE` que restringen
el universo de candidatos. Hay **tres patrones**, y la elección impacta el rendimiento y el recall:

- **Pre-filtering.** Aplica el `WHERE` estructural **antes** de la búsqueda vectorial: pgvector
  restringe candidatos y solo después aplica la distancia sobre el subconjunto.

  ```sql
  SELECT c.id, c.content, c.metadata, c.embedding <=> :query_embedding AS distance
  FROM chunks c
  JOIN documents d ON c.document_id = d.id
  WHERE d.sector = ANY(:sectors)
    AND d.project_year >= :year_min
    AND c.embedding <=> :query_embedding < :distance_threshold
  ORDER BY c.embedding <=> :query_embedding
  LIMIT :top_k;
  ```

  **Correcto cuando el filtro tiene alta selectividad** (deja un subconjunto pequeño). Si
  `sector = 'healthcare' AND project_year >= 2022` deja solo el 5 %, pgvector busca sobre 50 chunks en
  lugar de 1.000. Durante años se advirtió que pre-filtering "destruía el índice HNSW" (caía a *seq
  scan*); **desde pgvector 0.7 los *iterative scans* sobre HNSW filtrado** permiten navegar el grafo
  descartando candidatos que no cumplen el `WHERE`. Ya no es catastrófico, y para selectividades por
  debajo del 20 % el rendimiento es razonable. **Estrategia por defecto del programa.**

- **Post-filtering.** Invierte el orden: busca vectorialmente con `K` ampliado (`wide_k = top_k × 3`)
  y **después** aplica el `WHERE`. **Correcto cuando el filtro tiene baja selectividad** (elimina poco)
  y el índice HNSW funciona mejor sin restricciones. **Riesgo:** perder recall si el filtro es muy
  selectivo (si `wide_k=50` pero solo 2 cumplen el filtro, has fallado y deberías haber subido
  `wide_k`); sin instrumentación, no te enteras.

- **In-query filtering.** La fusión moderna que pgvector facilita gracias a los *iterative scans*: la
  query se escribe como pre-filtering pero **el optimizador decide internamente** la mejor estrategia
  según la selectividad estimada. El "pre" vs "post" se convierte en una decisión del planner, no algo
  que escribas tú. **Es la query que ejecutas en producción.**

Los **cuatro filtros** que el proyecto expone en la API de retrieval: `sectors` (lista de sectores),
`project_year_range` (rango de años), `tech_stack` (tecnologías, operador JSONB `@>` sobre metadata) y
`chunk_types` (limitar a tipos del esquema de la Sesión 7: `scope_block`, `line_item`, `phase`). El
patrón `(:filter IS NULL OR ...)` los hace **opcionales**: si el reformulador no extrajo el campo,
viene `null` y el filtro se ignora. Esto **encadena directamente con la salida estructurada de la
Parte 2**: cada campo del esquema Pydantic mapea a un filtro opcional, y la coherencia entre capas se
mantiene por construcción.

## 3.5 Cuatro anti-patrones que el sistema invita a cometer

1. **Subir K para arreglar la calidad.** Si tus resultados son malos, la solución no es traer *más*,
   es traer *mejor*. Sumar ruido al contexto no mejora la respuesta. Subir K solo tiene sentido cuando
   una inspección manual confirma que hay chunks relevantes más allá del top-10.
2. **Confiar en el LLM como filtro final.** "Metemos 20 chunks y que el modelo elija." El modelo **no
   es un buen retriever**: no compara chunks sistemáticamente, no rechaza lo irrelevante con
   disciplina, y bajo presión narrativa acaba sintetizando información que debería haber ignorado. **El
   filtrado se hace en el retriever; el LLM sintetiza, no filtra.**
3. **Omitir el threshold porque "casi siempre hay algo".** A veces cierto, pero como decisión
   arquitectónica es frágil: el día que falle, generará una estimación basada en chunks irrelevantes y
   nadie lo notará hasta que un cliente cuestione el resultado.
4. **Mezclar `chunk_types` sin filtrar.** Un `scope_block` (bloque funcional) y un `line_item` (tarea
   presupuestada) tienen utilidades distintas para la generación. Si la query es sobre coste, quieres
   `line_item`; si es sobre alcance funcional, `scope_block`. Filtrar por tipo cuando el reformulador
   da pistas claras **es gratis y mejora la precisión**.

## 3.6 Recall vs precision: el trade-off real

Detrás de todo está un debate de fondo: el sistema elige entre **recall** (recuperar todo lo
potencialmente relevante, aunque incluya ruido) y **precision** (recuperar solo lo claramente
relevante, aunque deje fuera alguna joya). **No se pueden maximizar a la vez.**

- En RAG **didáctico**, la convención es priorizar **recall**: traer más para que el LLM tenga material.
- En RAG **de producción**, sobre todo cuando la salida tiene consecuencias económicas —y una
  estimación de software las tiene—, la posición correcta es priorizar **precision**: traer menos pero
  mejor, aceptar que a veces el sistema responde "no tengo evidencia suficiente", y dejar para etapas
  posteriores (reranking en la Sesión 10) los mecanismos que suben el recall sin sacrificar precision.

La razón es una **asimetría de errores**: una alucinación apoyada en chunks parcialmente relevantes
(una estimación de 250.000 € sin evidencia sólida) es **más peligrosa** que un "no lo sé" honesto. La
primera crea una expectativa que ni la empresa ni el cliente pueden honrar; el segundo preserva la
confianza en las estimaciones que sí produce. Esa asimetría es lo que justifica favorecer precision
sobre recall en este dominio.

---

# PARTE 4 — Augmentation y generación: ensamblar contexto y forzar grounding

> **Para cualquiera:** ya tienes los chunks correctos. Falta "dárselos" al modelo. La forma ingenua
> —pegarlos uno detrás de otro y mandarlos— es justo la que produce respuestas inventadas. Esta parte
> cubre cómo **empaquetar** el contexto (etiquetas, orden, recorte) y cómo **instruir** al modelo
> (usa solo esto, cita las fuentes, di "no sé" cuando no tengas datos) para que la calidad del
> retrieval no se desperdicie.

## 4.1 Por qué `"\n\n".join(chunks)` falla

La tentación que enseña medio internet:

```python
context = "\n\n".join([chunk.content for chunk in retrieved_chunks])
prompt = f"Contexto:\n{context}\n\nGenera una estimación para: {query}"
response = client.responses.create(model="gpt-5", input=[{"role": "user", "content": prompt}])
```

No lanza excepción, pero produce con regularidad **tres patologías**:

1. **Citas inventadas.** Sin instrucciones de cómo referenciar, el modelo fabrica identificadores
   plausibles ("según el proyecto 312…") que no estaban entre los chunks.
2. **Mezclas cruzadas.** Combina información de chunks distintos como si fuera un único proyecto,
   generando una estimación que no corresponde a ningún presupuesto real.
3. **Respuesta sin contexto.** La más sutil: el modelo **ignora silenciosamente** los chunks y
   responde con su conocimiento general, dándote la falsa impresión de que el retrieval funcionó.

Causa común: el modelo **no ha recibido instrucciones** sobre cómo tratar el bloque de texto. No sabe
si es contexto autoritativo, sugerencias ignorables o documentación a citar; no sabe si puede negarse
a generar; no sabe qué fuente atribuir a cada afirmación. **Augmentation no es "meter chunks en el
prompt"; es construir un input que le diga explícitamente todas esas cosas.**

## 4.2 Delimitadores XML: que el modelo distinga contexto de instrucción

Los modelos modernos están entrenados con cantidades masivas de XML —y con las convenciones que
Anthropic y OpenAI han popularizado—, así que reconocen etiquetas como `<source>`, `<context>` o
`<document>` como **límites semánticamente significativos**. La función de ensamblado vive en
`generation/context_assembler.py`:

```python
def build_context_block(chunks: list[RetrievedChunk]) -> str:
    blocks = []
    for chunk in chunks:
        meta = [
            f'id="{chunk.id}"', f'sector="{chunk.sector}"',
            f'project_year="{chunk.project_year}"', f'chunk_type="{chunk.chunk_type}"',
            f'distance="{chunk.distance:.3f}"',
        ]
        attrs = " ".join(meta)
        blocks.append(f"<source {attrs}>\n{chunk.content.strip()}\n</source>")
    return "\n\n".join(blocks)
```

Tres decisiones deliberadas:

- **La metadata va como atributos XML, no embebida en el texto.** Permite al modelo citar con
  precisión ("según `source id=142`") y filtrar mentalmente por sector; meterla en prosa obligaría al
  modelo a parsearla cada vez.
- **Se incluye la `distance` entre los atributos.** Debatible —algunos sistemas la ocultan para que el
  modelo no se sobreajuste a los chunks más cercanos—; el programa la expone porque **da al modelo una
  señal explícita de relevancia** que puede usar al ponderar evidencia.
- **El delimitador es `<source>`, en singular**, no `<context>` ni `<document>`: la etiqueta se elige
  por su connotación —el modelo trata cada `<source>` como una **unidad atribuible de información**,
  justo lo que queremos para forzar citaciones.

Alternativa frecuente: **JSON delimited context** (un array de objetos con `id`, `content`, metadata).
Funciona, pero tiene un fallo silencioso: los modelos tienden a "leer" estructuras JSON como **datos a
interpretar**, no como instrucciones autoritativas. Un `"content": "..."` se trata a veces como
descripción, no como contexto de referencia. El delimitador XML lleva la connotación correcta de
"esto es contenido de referencia que debes consultar".

## 4.3 Orden de los chunks: *lost in the middle* es real y predecible

La intuición ingenua es que el orden da igual. La evidencia dice lo contrario, de forma medible. El
paper de referencia es *"Lost in the Middle: How Language Models Use Long Contexts"* (Liu et al.,
2023): construyen prompts con N documentos de los cuales solo uno es relevante y mueven su posición. La
curva de precisión resultante tiene **forma de U** — el modelo recupera bien la información al
**principio** o al **final** del contexto, pero la pierde con regularidad cuando está **en el medio**
(precisión que cae hasta veinte puntos). Replicado en GPT-4, Claude y modelos posteriores; **no es un
artefacto de una arquitectura concreta**.

Implicación: si colocas diez chunks por distancia ascendente, el `rank=1` (principio) y el `rank=10`
(final) reciben atención privilegiada, y los `rank=4-7` caen en la **zona de penalización**. Tu
retrieval hace el trabajo correcto pero el modelo degrada la mitad de tus chunks **por geometría del
prompt**.

Dos estrategias; el programa adopta la primera por simplicidad:

- **Most-relevant-first** (por defecto): dejar los chunks en orden de distancia ascendente. Con K=5–10
  (rango típico del programa) el efecto es modesto y los chunks más relevantes ya están en las
  posiciones privilegiadas del principio.
- **Estrategia U-pattern** (para K=15–20, donde el efecto se agrava): reordenar para que `rank=1` vaya
  al principio, `rank=2` al final, `rank=3` en segunda posición, etc.

  ```python
  def reorder_u_pattern(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
      front, back = [], []
      for i, chunk in enumerate(chunks):
          (front if i % 2 == 0 else back).append(chunk)
      return front + list(reversed(back))
  ```

  Queda como **opción configurable** en `context_assembler.py`, no activa por defecto. Cuándo
  activarla es decisión del operador, basada en métricas: si la calidad empeora notablemente al subir
  K, *lost in the middle* está penalizando y el *reorder* vale la pena.

## 4.4 Truncamiento defensivo: cortar el chunk completo, no el contenido

Cuando el bloque de contexto excede el presupuesto de tokens, hay que descartar contenido. El
antipatrón es **truncar por caracteres** al llegar al límite: el último chunk queda a medias, pierde
coherencia, cualquier cita a su `id` es estructuralmente inválida (el modelo citó un proyecto del que
solo vio la mitad), y se desperdician todos sus tokens. **Regla: truncar a nivel de chunk completo —
si no cabe entero, no entra.**

```python
def truncate_to_token_budget(chunks, max_context_tokens, encoder):
    selected, used_tokens = [], 0
    for chunk in chunks:  # ya ordenados por relevancia
        wrapped_size = len(encoder.encode(_wrap_chunk(chunk)))
        if used_tokens + wrapped_size > max_context_tokens:
            break
        selected.append(chunk)
        used_tokens += wrapped_size
    return selected
```

Dos detalles:

- **`_wrap_chunk(chunk)`** cuenta los tokens del chunk **ya envuelto con sus delimitadores XML y
  metadata**, no solo del contenido. Los wrappers cuestan 30–50 tokens por chunk; ignorarlos deja al
  sistema con un *budget* sistemáticamente optimista y empezarás a recortar cuando ya excediste el
  límite real.
- **Dejar margen para la salida.** El *budget* del modelo es total (input + output). Regla heurística:
  reservar **15 % para la salida** y **5 % para overhead** de prompt (system message, instrucciones,
  query). Sobre una ventana de 200k, eso deja ~160k para el contexto recuperado —más de lo que
  cualquier retrieval razonable necesita.

## 4.5 El prompt de generación: *grounding* explícito y política de "no sé"

La diferencia entre un prompt mediocre y uno disciplinado está en **cuatro elementos**: restricción de
fuentes, obligación de citar, política de insuficiencia y distinción evidencia/asunción.

```python
ESTIMATOR_SYSTEM_PROMPT = """You are a senior software estimation assistant.
Your job is to produce structured budget estimates for new software projects
based on historical reference projects.

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

5. Distinguish evidence-backed components from assumptions you must make
   to bridge gaps in the historical data.

Output must conform to the provided JSON schema."""
```

Cada regla está por una razón:

- **Regla 1** — *grounding* explícito con `ONLY` en mayúsculas; el contraste tipográfico es una señal
  que los modelos reconocen como énfasis y mejora la adherencia.
- **Regla 2** — fuerza la atribución: sin esta línea el modelo cita "a veces"; con ella, citar es parte
  del contrato.
- **Regla 3** — reduce las citas inventadas dando un camino explícito ("surface as assumption") para
  decir "no tengo evidencia".
- **Regla 4** — el contrato más importante: el modelo **puede negarse a estimar** (`confidence =
  "insufficient"`), activando el camino *downstream* que el orquestador maneja con criterio.
- **Regla 5** — separa numéricamente lo apoyado en el corpus de lo que requiere extrapolación.

El **user prompt** combina el bloque de contexto con la query estructurada y **repite** la instrucción
crítica al final:

```python
def build_user_prompt(context_block: str, structured_query: EstimationQuery) -> str:
    return f"""Historical reference projects:

{context_block}

New project to estimate:

{structured_query.model_dump_json(indent=2)}

Generate a structured estimate. Cite sources for every quantitative claim.
If the historical context does not cover this kind of project sufficiently,
return confidence="insufficient" and explain what is missing."""
```

La repetición es deliberada: el system prompt **define** las reglas; el user prompt las **reactiva**
justo antes de generar. Los modelos atienden de forma especialmente fuerte al **final del prompt**, y
poner ahí el recordatorio crítico mejora la tasa de respuestas honestas cuando el contexto es flojo.

## 4.6 Esquema de salida: structured output como contrato

Misma mecánica que el reformulador (Responses API, `text.format`, `strict: True`), pero el esquema
captura toda la estructura de la estimación más los metadatos de trazabilidad:

```python
class SourceCitation(BaseModel):
    source_id: int
    relevance: Literal["primary", "supporting", "tangential"]
    used_for: str = Field(description="Which component this source informs")

class Assumption(BaseModel):
    description: str
    impact: Literal["high", "medium", "low"]
    rationale: str

class CostComponent(BaseModel):
    name: str
    engineer_days: int
    sources: list[int] = Field(description="Source ids that support this component")

class Estimate(BaseModel):
    total_engineer_days: int | None
    cost_breakdown: list[CostComponent]
    duration_weeks: int | None
    sources: list[SourceCitation]
    assumptions: list[Assumption]
    confidence: Literal["high", "medium", "low", "insufficient"]
    reasoning: str
    insufficient_context_explanation: str | None = Field(default=None,
        description="If confidence is 'insufficient', explain what is missing")
```

Decisiones codificadas en el esquema:

- `total_engineer_days` y `duration_weeks` son `int | None`: cuando `confidence == "insufficient"`, el
  modelo debe devolverlos a `None` **en lugar de inventarse un número**.
- Cada `CostComponent` carga su **propia lista de `sources`** → trazabilidad fina por componente, no
  solo global.
- `Assumption` separa "qué se asume" de "por qué" para que la revisión humana pueda evaluar la asunción.
- `insufficient_context_explanation` activa el **soft-fail simétrico** al del retriever: cuando el
  modelo no puede estimar, captura el motivo en un campo dedicado en lugar de en una salida ad-hoc.

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
estimate = Estimate.model_validate_json(response.output_text)
```

Dos parámetros con matiz:

- **`gpt-5` para generación** (no `gpt-5-mini` como el reformulador): sintetizar evidencia de múltiples
  fuentes, razonar sobre componentes y decidir cuándo no estimar es genuinamente complejo y justifica
  el modelo más capaz.
- **`reasoning.effort="medium"`** sustituye al antiguo `temperature`, que **ya no es válido en gpt-5**
  (está en la guía de *"Deprecated parameters in reasoning models"* de la Sesión 1). Valores: `low`
  (estimaciones superficiales), `medium` (el punto razonable), `high` (más latencia y coste sin mejora
  medible para este caso).

## 4.8 Validación post-generación: cerrar el bucle

El structured output garantiza la **forma** (campos, tipos, literales válidos), pero **no la coherencia
semántica** con los chunks. Tres validaciones:

1. **Citaciones** (crítica, no opcional). El modelo a veces cita un `source_id` que no estaba entre
   los recuperados (fallo de atención, confusión entre IDs, alucinación). La validación es trivial:

   ```python
   def validate_citations(estimate: Estimate, retrieved_chunks) -> list[int]:
       valid_ids = {c.id for c in retrieved_chunks}
       cited_ids = set()
       cited_ids.update(c.source_id for c in estimate.sources)
       for component in estimate.cost_breakdown:
           cited_ids.update(component.sources)
       return sorted(cited_ids - valid_ids)  # IDs inventados
   ```

   Si devuelve algo no vacío, el orquestador tiene tres opciones: **reintentar** la generación con
   feedback ("your previous response cited invalid source ids: …") —por defecto, máximo un reintento—;
   **degradar la confianza** automáticamente (de `high` a `medium` + anotar el incidente); o **rechazar
   la respuesta** y devolver "estimación no fiable, requiere revisión manual". El programa usa la
   primera y cae a la tercera si el reintento también falla.

2. **Coherencia de confidence.** Si `confidence == "insufficient"`, debe existir
   `insufficient_context_explanation` y los campos numéricos deben ser `None`. Cualquier inconsistencia
   ("insufficient" pero con números, o "high" sin citar fuentes) se trata como respuesta malformada y se
   reintenta.

3. **Sanidad numérica.** Una estimación de cien mil días-ingeniero o de tres semanas para un proyecto
   B2B complejo es probablemente un fallo. El sistema **marca esos casos para revisión sin bloquear**
   la respuesta: la sanidad ayuda al humano que revisa, no es un guardarraíl absoluto.

> Flujo de validación: `LLM call → schema validation (campos/tipos) → citation validation (sin
> source_id fabricados) → confidence + sanity → Estimate ready`. Los dos primeros pueden disparar un
> reintento con feedback al modelo.

## 4.9 Trade-offs honestos

- **Control de "creatividad".** La intuición de muchos ingenieros sigue pidiendo bajar `temperature` a
  cero, pero **el parámetro ya no existe en gpt-5**. En *reasoning models* el efecto equivalente
  (respuestas más deterministas) se obtiene con `reasoning.effort` bajo + prompts muy restrictivos. La
  verdad operativa: con un prompt bien estructurado y structured output `strict`, la variabilidad
  inter-llamadas ya es muy baja **sin tocar parámetros** —el modelo está restringido por la forma de
  salida y las reglas del system prompt.
- **Instrucción estricta vs flexible.** Vuelve la asimetría de errores de la Parte 3. El system prompt
  es severo ("ONLY", "never invent", "return insufficient if needed"). Esa severidad tiene un coste —el
  modelo a veces se niega cuando un humano habría extrapolado— pero **el ahorro en alucinaciones lo
  compensa**. La alternativa flexible ("you may extrapolate when reasonable") produce más cobertura
  aparente y mucha menos fiabilidad real. Para un sistema cuyo output influye en presupuestos, **severo
  es mejor que cómplice**.
- **Coste de las citaciones obligatorias.** Forzar citas aumenta los tokens de salida un **10–20 %**
  (cada `SourceCitation` son 5–10 tokens; un breakdown de diez componentes con citas duplica el tamaño
  de la respuesta). Sobre miles de peticiones/mes no es despreciable. Pero la trazabilidad que habilitan
  es lo que distingue una estimación "que el sistema produjo" de una "que el sistema puede defender", y
  para estimación financiera esa distinción es crítica.

---

# PARTE 5 — La capa de datos como servicio: aislar y securizar el retriever

> **Para cualquiera:** ya tienes el flujo RAG completo funcionando dentro de un proceso. Eso es un
> MVP. El problema aparece a los dos o tres meses: el equipo comercial quiere **buscar proyectos
> similares** sin generar estimación (solo ver presupuestos parecidos), y de repente "buscar" y
> "estimar" son **dos servicios distintos** que casualmente comparten código. Tratarlos como uno solo
> —misma puerta, misma llave, mismo límite de uso— paga peaje a largo plazo. Esta parte separa las dos
> capas y las convierte en un servicio que un equipo puede operar **sin miedo durante años**.

## 5.1 El problema: dos servicios lógicos distintos

El endpoint público del MVP es uno solo (`POST /v1/estimate`) y detrás vive toda la lógica. Cuando
surge la necesidad de exponer solo el retrieval, las opciones tentadoras —añadir
`?retrieval_only=true` al endpoint existente, o duplicar a `/v1/estimate` + `/v1/retrieve`— crean
problemas que no se ven hasta meses después. Tres tensiones apuntan en la misma dirección:

- **Blast radius.** Cuando la Sesión 10 introduzca reranking sobre el retriever, cualquier cambio
  tocaría el endpoint de estimación aunque la generación no varíe. Radio de impacto innecesariamente
  amplio.
- **Rate limiting diferenciado.** El endpoint de estimación necesita un régimen **severo** (cada
  llamada cuesta euros en tokens y segundos en latencia); el de retrieval puede ser **mucho más
  permisivo** (milisegundos y casi nada de dinero). El mismo límite o estrangula al consumidor barato o
  deja al caro sin protección.
- **Granularidad de credenciales.** Dar a un compañero acceso al retrieval para un script ad-hoc no
  debería darle permiso para gastar el presupuesto de LLM.

> **El retriever y el generador son dos servicios lógicos distintos que casualmente comparten
> codebase.** El programa aplica el patrón inverso: **dos routers separados, dos contratos públicos,
> dos regímenes de seguridad, y un cliente que invoca al servicio desde el backend de negocio.**

## 5.2 Dos routers, dos contratos

FastAPI organiza endpoints en `APIRouter`, un mecanismo de composición. La estructura final del
servicio IA al cierre de la Sesión 9:

```
src/estimator/
├── api/
│   ├── main.py        ← monta ambos routers
│   ├── security.py    ← API keys, comparación constant-time
│   └── routers/
│       ├── retrieval.py   ← POST /v1/retrieval/search
│       └── estimate.py    ← POST /v1/estimate/from-transcript
├── retrieval/         (query_reformulator.py, retriever.py)
└── generation/        (context_assembler.py, prompt_builder.py, estimator.py)
```

```python
from fastapi import FastAPI
from estimator.api.routers import retrieval, estimate

app = FastAPI(title="Estimator AI Service", version="0.9.0")
app.include_router(retrieval.router, prefix="/v1/retrieval", tags=["retrieval"])
app.include_router(estimate.router, prefix="/v1/estimate", tags=["estimate"])
```

El router de **retrieval** expone un contrato con palancas operativas y una respuesta **exhaustiva**:

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

@router.post("/search", response_model=SearchResponse)
def search(req: SearchRequest, _: str = Depends(require_retrieval_key)):
    result = search_chunks(query_text=req.query_text, top_k=req.top_k,
        distance_threshold=req.distance_threshold, sectors=req.sectors,
        project_year_min=req.project_year_min, chunk_types=req.chunk_types)
    return SearchResponse(
        chunks=[SearchResponseChunk(**c.model_dump()) for c in result.chunks],
        low_confidence=len(result.chunks) == 0,
        total_candidates_considered=result.candidates_evaluated)
```

El router de **estimate** tiene un contrato más simple porque encapsula más:

```python
class EstimateRequest(BaseModel):
    transcript: str = Field(min_length=100, max_length=50000)
    idempotency_key: str | None = Field(default=None, max_length=128)

@router.post("/from-transcript", response_model=Estimate)
def estimate(req: EstimateRequest, _: str = Depends(require_estimate_key)):
    return estimate_from_transcript(transcript=req.transcript,
                                    idempotency_key=req.idempotency_key)
```

**La asimetría entre los dos contratos es deliberada.** Retrieval expone palancas (`top_k`,
`distance_threshold`, filtros) porque sus consumidores son equipos internos que quieren ajustar el
comportamiento. Estimate expone **solo el input mínimo** (la transcripción) porque toda la complejidad
debe estar gestionada por el servicio, no por el cliente: el backend en Rails no debería saber qué
`top_k` se usa internamente; solo necesita "le paso una transcripción, me devuelve una estimación
validada". Además, la respuesta de retrieval incluye `low_confidence` y `total_candidates_considered`
como campos **de primer nivel** (no anidados ni opcionales): el consumidor sabe siempre si el retriever
encontró material relevante.

## 5.3 API Keys y comparación *constant-time*

El consumidor del servicio IA es siempre **otro servicio interno** (el backend de negocio o scripts del
equipo), no un usuario final con identidad personal. Para ese patrón, **API Keys es lo correcto**:
simple, sin estado, sin flujo OAuth, sin servidor de identidad. Dos cambios respecto a una sola clave
global: hay **dos claves separadas** (una para retrieval, otra para estimate) y la comparación se hace
con `secrets.compare_digest`, no con `==`.

```python
import os, secrets
from fastapi import Header, HTTPException, status

RETRIEVAL_API_KEY = os.environ["RETRIEVAL_API_KEY"]
ESTIMATE_API_KEY = os.environ["ESTIMATE_API_KEY"]

def require_retrieval_key(x_api_key: str = Header(...)) -> str:
    if not secrets.compare_digest(x_api_key, RETRIEVAL_API_KEY):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return x_api_key

def require_estimate_key(x_api_key: str = Header(...)) -> str:
    if not secrets.compare_digest(x_api_key, ESTIMATE_API_KEY):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return x_api_key
```

**Por qué `compare_digest` y no `==`.** La comparación nativa de strings es **non-constant-time**:
termina en cuanto encuentra el primer carácter distinto. Eso crea un **canal lateral medible** —un
atacante que mide cuánto tarda el servidor en responder con `401` puede inferir, byte a byte, cuán cerca
está su clave de la real (*timing attack*). Aunque la latencia diferencial es de microsegundos, sobre
una red local con muchas peticiones es explotable. `compare_digest` tarda **lo mismo
independientemente** de cuán "cerca" esté la clave. **El coste de usar la versión segura es cero** (la
misma línea de código), así que no hay justificación para usar `==` con secretos.

**Rotación de claves** (fuera del scope de S09 pero el patrón conviene conocerlo): las API Keys deben
rotarse periódicamente, y la rotación debe ser **graceful** —durante la ventana, dos claves válidas a la
vez (`RETRIEVAL_API_KEY` y `RETRIEVAL_API_KEY_PREVIOUS`) para que el consumidor actualice su
configuración sin *downtime*; cuando todos han migrado, se retira la antigua.

## 5.4 Rate limiting diferenciado con `slowapi`

`slowapi` se integra de forma natural con FastAPI (usa Starlette, se monta como middleware). El detalle
clave: el rate limiting se hace **por API key, no por IP**.

```python
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware

def get_api_key(request) -> str:
    return request.headers.get("x-api-key", get_remote_address(request))

limiter = Limiter(key_func=get_api_key)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
```

**Por qué por API key y no por IP.** Si el backend de negocio comparte una sola IP (vive tras NAT o un
proxy compartido), el rate limiting por IP sería trivial de saturar y bloquearía a usuarios legítimos.
Por API key, cada consumidor tiene su propio cubo de tokens. Los dos regímenes se aplican como
decoradores específicos:

```python
@router.post("/search", response_model=SearchResponse)
@limiter.limit("120/minute")
def search(request, req: SearchRequest, _: str = Depends(require_retrieval_key)): ...

@router.post("/from-transcript", response_model=Estimate)
@limiter.limit("10/minute")
def estimate(request, req: EstimateRequest, _: str = Depends(require_estimate_key)): ...
```

**Los números (120/min retrieval, 10/min estimate)** son una primera aproximación basada en costes
esperados: retrieval cuesta ~1 ms y nada de infraestructura → 120/min es generoso pero razonable;
estimate cuesta 5–15 s y 0,20–1 € en tokens → 10/min = 600/hora, más que suficiente para un equipo
comercial y una **protección contra runaway costs**. No son universales; el operador los calibra
observando el uso real.

Cuando se excede el límite, la respuesta debe ser **informativa**:

```python
def custom_rate_limit_handler(request, exc):
    return JSONResponse(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"error": "rate_limit_exceeded", "limit": str(exc.detail),
                 "retry_after_seconds": 60},
        headers={"Retry-After": "60"})
```

El header **`Retry-After`** es el estándar HTTP que los clientes bien construidos consultan; el campo
`retry_after_seconds` en el body es la versión amigable para frontends que prefieren JSON.

## 5.5 Idempotencia: peticiones duplicadas, una sola estimación

El endpoint de estimate tiene una propiedad que el de retrieval no: **cada llamada cuesta**. Si el
backend reintenta una petición porque su HTTP client cortó el socket por timeout, no quieres generar una
segunda estimación, duplicar el coste y producir un resultado distinto (por la variabilidad del LLM). El
patrón estándar son **idempotency keys**.

El contrato: el cliente envía un `idempotency_key` (un UUID que él genera) en cada petición. El servicio
almacena en una caché temporal (Redis, o memoria en MVP) la asociación `idempotency_key → estimate`. Si
llega una key ya conocida, devuelve la estimación cacheada **sin volver a llamar al LLM**.

```python
def estimate_from_transcript(transcript: str, idempotency_key: str | None = None) -> Estimate:
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

- **TTL de 24 h:** demasiado corto y los reintentos legítimos caen fuera de la ventana; demasiado largo
  y la caché se vuelve un repositorio implícito de estimaciones históricas (eso debería estar en la BBDD
  del backend, no en la caché del servicio IA). 24 h cubre el escenario realista.
- **Sutileza:** el cliente puede mandar la misma key con una `transcript` ligeramente distinta (editó el
  texto y reintentó). La protección estándar es **hashear la transcripción** y guardar el hash junto a la
  estimación; si una petición posterior con la misma key trae un hash distinto, se devuelve un **`409
  Conflict`**. Mejora opcional fuera del scope de S09.

## 5.6 Logging estructurado por etapa

El servicio tiene cinco etapas internas que fallan de formas distintas (reformulación, retrieval,
ensamblado, generación, validación) y el debug eficiente exige **distinguirlas**. El programa adopta
`structlog` con salida JSON para que cada línea sea parseable por herramientas de observabilidad
(Logfire, Langfuse, Helicone — detalle en S15).

```python
import structlog, time, uuid
from contextlib import contextmanager

logger = structlog.get_logger()

@contextmanager
def log_stage(stage: str, request_id: str, **context):
    start = time.perf_counter()
    log = logger.bind(stage=stage, request_id=request_id, **context)
    log.info("stage.started")
    try:
        yield log
        duration_ms = (time.perf_counter() - start) * 1000
        log.info("stage.completed", duration_ms=round(duration_ms, 2))
    except Exception:
        duration_ms = (time.perf_counter() - start) * 1000
        log.exception("stage.failed", duration_ms=round(duration_ms, 2))
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

- El **`request_id`** ata todas las líneas de una petición en una traza coherente; sin él, los logs de
  cinco etapas se entremezclan con los de peticiones concurrentes y es imposible reconstruir qué pasó.
  Se incluye también como header **`X-Request-ID`** en la respuesta, para que el backend correlacione sus
  logs con los del servicio.
- **Dos atributos por etapa siempre:** `duration_ms` (detectar regresiones de latencia) y un campo
  específico de debug (`sectors` en retrieval, `chunks` en assembly, `confidence` en validation). Son
  los campos que, cuando dentro de tres meses un cliente reporte una estimación rara, permiten
  reconstruir la cadena de decisiones **sin reproducir la petición**.

## 5.7 El cliente Ruby desde el backend de negocio

El patrón es independiente del stack (cualquier HTTP client sirve); se muestra en Ruby por alineación
con la implementación de referencia (Rails + Faraday):

```ruby
class EstimatorClient
  ESTIMATE_TIMEOUT = 30  # seconds
  RETRY_OPTIONS = { max: 2, interval: 1.5, backoff_factor: 2,
                    retry_statuses: [502, 503, 504], methods: [:post] }.freeze

  def initialize(base_url:, api_key:)
    @conn = Faraday.new(url: base_url) do |f|
      f.request :json
      f.request :retry, RETRY_OPTIONS
      f.response :json, content_type: /\bjson$/
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

Tres decisiones:

- **Timeouts diferenciados:** `open_timeout` de 5 s (detectar rápido que el servicio está caído) y
  `timeout` total de 30 s (cubrir el peor caso de una llamada al LLM con `reasoning.effort` alto). Sin
  ellos, Faraday cae a 60 s para todo y el usuario se queda mirando un spinner.
- **Retry restringido a `5xx`** (`502/503/504`, fallo transitorio): reintentar un `400`/`401` no tiene
  sentido (el servidor dice que la petición está mal) y reintentar un `500` puro es ambiguo.
- **`idempotency_key` generado por defecto** con `SecureRandom.uuid`: cada llamada lleva una key aunque
  el código que llama no se preocupe del tema. Si el retry de Faraday se activa, la **misma key** viaja
  al servicio y el patrón de idempotencia se activa **automáticamente**.

## 5.8 Trade-offs honestos

- **API Key vs JWT vs mTLS.** API Key tiene dos limitaciones reales: no lleva identidad más allá de
  "alguien que tiene esta clave", y si se filtra, cualquiera la usa hasta que se rote. JWT mitiga la
  primera (los tokens llevan *claims*) pero no la segunda; mTLS mitiga ambas a costa de complejidad
  operativa significativa (gestión de certificados, CA, rotación más compleja). Para un servicio interno
  cuyo único consumidor es el backend en infraestructura controlada, **API Key es el mejor
  coste/beneficio**. Si se expusiera a múltiples consumidores externos con identidades distintas, JWT
  sería lo correcto; con *service mesh* (Istio, Linkerd), mTLS sería casi gratuito. **Depende del
  contexto operativo, no de una preferencia universal.**
- **OWASP API Security Top 10** es la referencia de lectura complementaria. Aunque el servicio solo
  aplique directamente dos o tres ítems, lo importante es interiorizar el reflejo de **revisar la lista
  cada vez que se añade un endpoint nuevo**.
- **Rate limiting in-memory vs distribuido.** `slowapi` por defecto usa memoria del proceso. Si el
  servicio se despliega con **múltiples workers** (gunicorn `-w 4`) o varias instancias tras un load
  balancer, cada uno lleva su propia cuenta y el límite efectivo **se multiplica por el número de
  workers**. Aceptable para el MVP (un worker, un contenedor); S15 introduce Redis como backend cuando el
  sistema escale horizontalmente. **El cambio es de configuración, no de código** (`slowapi` soporta
  Redis nativamente).

---

## Cómo conecta con nuestro ejercicio y con el directo

El **ejercicio pre-sesión** consiste en correr la transcripción ambigua sobre el CAG actual y
identificar **cinco fallos**, que mapean directamente a las cuatro etapas: la query cruda no recupera
(Query), los chunks son irrelevantes o están mezclados (Retrieval), la concatenación naive produce
respuestas pobres (Augmentation), el modelo inventa o no cita (Generation). Llegar con esa
correspondencia mental hecha es lo que más valor aporta.

La **sesión en vivo** son seis bloques, uno por pieza del flujo:

1. **CAG vs RAG en paralelo:** correr la misma transcripción ambigua por el CAG de la Sesión 5 y un
   esqueleto RAG, midiendo respuesta, latencia, coste en tokens y trazabilidad.
2. **Iterar la reformulación:** contrastar tres caminos sobre la misma transcripción —embedding crudo
   (baseline naive), extracción estructurada y HyDE— midiendo cuántos chunks recuperados pertenecen al
   sector y geografía correctos.
3. **Decisiones del reformulador:** ¿permitir inferir tecnologías no mencionadas? ¿marcar el sector como
   `null` ante ambigüedad? ¿extraer `scale="pilot"` de "dos clínicas piloto"?
4. **Parámetros del retriever:** variar `top_k` (3–30), `threshold` (0.5–0.8) y filtros, midiendo número
   de chunks devueltos, % del sector correcto y latencia mediana. El objetivo **no es encontrar los
   parámetros "óptimos"** (eso es folklore: lo óptimo hoy puede no serlo en seis meses) sino
   **interiorizar la sensibilidad** del sistema a cada palanca.
5. **El prompt de generación:** partir del prompt mínimo (concatenación raw) y añadir restricciones de
   una en una, observando cómo cambia la salida. Más una **demo deliberada de *lost in the middle***
   poniendo el chunk crítico en distintas posiciones.
6. **Cierre end-to-end y seguridad:** poner el rate limit del estimate absurdamente bajo (2/min), generar
   tres peticiones desde el cliente Ruby y observar el `429` + `Retry-After` + el efecto del
   `idempotency_key`. Más un escenario de seguridad: **filtrar deliberadamente una API key en un commit**
   y discutir la respuesta (rotación inmediata, deploy de la nueva clave, y por qué tener dos claves
   separadas limita el daño).

> **El cierre conceptual de la Sesión 9:** lo que has construido ya no es un script con un LLM detrás,
> es un **servicio operable** —contratos claros, autenticación diferenciada, rate limits razonables,
> idempotencia, logging estructurado y un cliente robusto. La Sesión 10 evolucionará la capa de
> retrieval (reranking, búsqueda híbrida) y esa evolución tocará **un solo módulo** —el retriever— sin
> que el endpoint de estimate, el rate limit, las credenciales o el cliente Ruby cambien. **El
> aislamiento es lo que hace esa evolución posible.**

### Chuleta de una página (lo imprescindible)

- **CAG → RAG:** CAG congela el contexto en el prompt; RAG lo **busca cada vez**. Cuatro etapas: **Query
  → Retrieval → Augmentation → Generation** (Lewis et al., 2020). RAG gana en frescura, techo de corpus,
  trazabilidad y resistencia a alucinación; **pierde** en latencia/coste (3–4 llamadas). CAG sigue siendo
  correcto para corpus pequeños y estables (Chan et al., 2024).
- **El mantra:** *"no prompt fixes bad retrieval"*. El **retrieval fija el techo** de calidad. Orden de
  debug: ¿chunks correctos? → ¿contexto bien montado? → ¿prompt fuerza grounding? → ¿modelo capaz? (en
  ese orden).
- **Query (reformulación):** embeber la transcripción cruda falla (longitud disuelve la señal, ruido
  ahoga keywords, anáforas contaminan). Cinco familias: rewriting, sub-query+RRF, step-back, HyDE,
  **extracción estructurada** (la elección: JSON Pydantic `strict` → texto compuesto **+ filtros de
  metadata**; única con artefacto inspectable y utilidad downstream). Fallback a rewriting si la
  validación falla; alarma si se activa >5 %.
- **Retrieval:** `top_k` **moderado y estable** (~10); **no subir K** para arreglar calidad. **Threshold**
  ≈ valle de la distribución empírica (0.6–0.65 para `text-embedding-3-small`); 0 resultados = info
  válida → **soft-fail** (`low_confidence`, no llamar al generador con contexto vacío). Filtros: **pre /
  post / in-query**; con pgvector ≥0.7 e *iterative scans*, lo escribes como pre y el **planner decide**.
  Operador de query ↔ operator class del índice (`<=>` ↔ `vector_cosine_ops`) o cae a *seq scan*.
- **Recall vs precision:** producción con consecuencias económicas → **prioriza precision**. Asimetría:
  una alucinación con número es peor que un "no lo sé" honesto.
- **Augmentation:** `"\n\n".join` produce citas inventadas, mezclas y respuestas sin contexto.
  Delimitadores **`<source id=... distance=...>`** (XML > JSON; metadata como atributos). Orden: **lost
  in the middle** (curva en U, Liu et al. 2023) → most-relevant-first por defecto, U-pattern si K≥15.
  Truncar a **chunk completo** contando wrappers; reservar **15 % salida + 5 % overhead**.
- **Generation:** prompt con **grounding** ("ONLY"), **obligación de citar**, **política de
  insuficiencia** (`confidence="insufficient"`, no forzar), evidencia vs asunción; repetir lo crítico al
  **final**. `gpt-5` + **`reasoning.effort`** (`temperature` muerto en gpt-5). Structured output `strict`
  como contrato. **Validar post-generación:** citaciones (sin `source_id` fabricados → reintento),
  coherencia de confidence, sanidad numérica.
- **Capa de datos como servicio:** retriever y generador = **dos servicios distintos**. Dos `APIRouter`
  (`/v1/retrieval/search` con palancas; `/v1/estimate/from-transcript` con input mínimo). **Dos API keys**
  separadas + `secrets.compare_digest` (no `==`, *timing attack*). **Rate limit por API key** (no IP) y
  diferenciado (120/min vs 10/min) + `429` con `Retry-After`. **Idempotencia** (`idempotency_key`, TTL
  24 h, hash de transcript → `409`). **Logging** `structlog` por etapa con `request_id`/`X-Request-ID` +
  `duration_ms`. Cliente con timeouts diferenciados + retry solo `5xx` + key por defecto. **API Key** es
  el mejor coste/beneficio para servicio interno (JWT/mTLS según contexto).
