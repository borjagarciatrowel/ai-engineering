# Sesión 10 — Recuperación avanzada (versión clara)

> Versión simplificada del resumen de los 6 artículos de la Sesión 10.
> Misma información, menos paja. Cada término técnico se explica en una frase.
> **Hilo conductor:** un sistema que busca presupuestos antiguos parecidos para estimar un proyecto nuevo.

---

## Glosario base (léelo una vez y vuelve cuando haga falta)

| Término | Qué es, en una frase |
|---|---|
| **Embedding** | Convertir un texto en una lista de números (un "vector") que captura su significado. Textos parecidos → vectores cercanos. |
| **Vector / espacio vectorial** | El embedding es un punto en un espacio de muchas dimensiones. "Cercanía" en ese espacio ≈ parecido de significado. |
| **Chunk** | Un trozo de documento (un párrafo, una sección). No indexamos documentos enteros, sino chunks. |
| **Similitud coseno / distancia** | La forma de medir cuán cerca están dos vectores. Distancia pequeña = muy parecidos. |
| **Top-k** | Los *k* primeros resultados de una búsqueda (top-5 = los 5 mejores). |
| **Recall (recuperación)** | ¿De todo lo relevante que existe, cuánto trajiste? |
| **Precisión** | ¿De lo que trajiste, cuánto era relevante de verdad? |
| **Latencia** | Cuánto tarda en responder. El coste que más duele. |
| **Pipeline** | La cadena de pasos por los que pasa una consulta hasta dar resultados. |
| **Metadatos** | Datos *sobre* el documento que no están en su texto: fecha, tecnología, sector, cliente. |

---

## La idea en una página

Un buscador que solo usa embeddings (lo que montamos en la Sesión 9) funciona como primera aproximación, pero **falla de 6 maneras predecibles**. La Sesión 10 da una herramienta para cada fallo:

| # | El fallo | La herramienta |
|---|----------|----------------|
| 1 | **Encuentra bien, pero ordena mal.** Trae lo relevante, pero el orden de los primeros no es fiable. | **Reranking** (Parte 1) |
| 2 | **No ve lo literal.** "Stripe" se le parece a "pasarela de pago", así que diluye el presupuesto que usó *exactamente* Stripe. | **Búsqueda híbrida** (Parte 3) |
| 3 | **La pregunta del usuario suele ser mala consulta.** Una transcripción de 40 min que mezcla 5 temas busca "cerca de todo y de nada". | **Expansión / descomposición** (Parte 4) |
| 4 | **Mezcla tipos de documento.** Presupuestos, transcripciones y docs técnicas revueltos se contaminan entre sí. | **Multi-índice + routing** (Parte 5) |
| 5 | **Ignora el tiempo y el contexto.** Un presupuesto de 2019 puede parecer perfecto y ser peligroso (precios y tecnología viejos). | **Filtrado temporal/contextual** (Parte 6) |
| 6 | **No sabemos si las mejoras mejoran algo.** "Parece que va mejor" no es un argumento. | **Medición con golden set** (Parte 2) |

> **La regla que vale más que cualquier técnica:** cada técnica es una **etapa que se enciende/apaga por configuración y se mide**. No se añade nada por estar de moda. Se añade solo si una tabla de dos columnas — *cuánto gana* vs *cuánto cuesta* — lo justifica. Toda pieza debe responder: **"¿qué aportas, exactamente, y cuánto cuestas?"**

---

# Parte 1 — Reranking: arreglar el orden

## El problema

Buscas un presupuesto para una **plataforma de e-commerce** y el buscador pone en **primera posición** un presupuesto de una **app de pagos**. No es un disparate (comparten vocabulario: pasarelas, checkout, seguridad), pero para estimar un e-commerce ese presupuesto es casi inútil — el grueso de un e-commerce está en catálogo e inventario, no en pagos.

> **La frase clave:** la búsqueda vectorial es **buena encontrando candidatos y mala ordenándolos.** La solución no es cambiar el modelo, sino **añadir una segunda etapa que ordene bien.**

## Por qué ordena mal

El modelo de embeddings es un **bi-encoder**:

> **Bi-encoder** = codifica cada texto **por su cuenta**, sin mirar con qué se va a comparar. Cada documento se convierte en su vector una sola vez (en la ingesta), y buscar es solo comparar vectores. Por eso es rápido y escala a millones de documentos.

Dos consecuencias de comprimir todo a un solo vector:
- **El vector promedia.** Un presupuesto de e-commerce con una sección pequeña de pagos, y uno de una app de pagos, quedan a distancias parecidas de una consulta que menciona pagos de pasada. El vector no distingue "habla sobre todo de esto" de "lo menciona entre otras diez cosas".
- **Consulta y documento nunca se miran juntos.** No hay ningún momento en que el modelo razone "esta consulta pide e-commerce, este doc va de pagos, se parecen pero no es lo que pide".

Resultado: entre los **50 más cercanos** los relevantes casi siempre están, pero **el orden dentro de esos 50 no es fiable.** Y al LLM solo le pasamos 5.

## La solución: cross-encoder

> **Cross-encoder** = mete consulta y documento **juntos** en el mismo modelo y devuelve directamente una nota de relevancia del par. Como los ve juntos, capta que "e-commerce" y "pagos" comparten campo pero no intención. Es preciso, pero **no se puede precalcular**: hay que ejecutarlo en cada consulta, por cada par.

| | Bi-encoder | Cross-encoder |
|---|---|---|
| Entrada | Texto a texto, por separado | Consulta + documento juntos |
| Salida | Un vector → similitud | Una nota de relevancia del par |
| ¿Precalculable? | Sí → búsqueda barata | No → una ejecución por par, cada vez |
| Orden | Impreciso | Preciso |
| Velocidad | Rápido | Lento |

**Ninguno, solo, sirve.** El truco es encadenarlos:

## Recall-then-rerank (las dos etapas)

```
Corpus (miles) ─► Búsqueda vectorial (bi-encoder, ~10ms) ─► Top-50 candidatos
                                                                   │
                          Top-5 ◄── Cross-encoder (~100-300ms) ◄────┘
                            │         (solo 50 pares, no el corpus)
                            ▼
                       Contexto del LLM
```

1. **Recall (red amplia y barata):** la búsqueda vectorial trae **top-50**. No pedimos orden fino, solo que los relevantes *estén* dentro.
2. **Precisión (reranking):** el cross-encoder puntúa **solo esos 50** y reordena. Nos quedamos con el **top-5**. Como solo evalúa 50 pares (no el corpus entero), el coste es asumible.

> **Dos reglas:** (1) el reranker **no toca el corpus** — el techo de calidad lo fija lo que entró en el top-50. (2) **reordena, no recupera.**

## Elegir los dos números

- **El 50 (conjunto amplio) fija el TECHO.** Si el relevante no entra en el top-50, ningún reranker lo rescata. Más candidatos = más margen pero más latencia. Para un corpus pequeño de empresa, **30–75** es razonable.
- **El 5 (conjunto final) lo dicta el LLM, no el reranker.** ¿Cuántos presupuestos caben sin diluir la instrucción? Dato clave: **5 bien elegidos baten a 15 mediocres.**

## Qué modelo usar

- **Local (gratis por consulta, datos no salen):** `ms-marco-MiniLM` (rápido pero **solo inglés**); para español, `mmarco-mMiniLMv2` (ligero) o `BAAI/bge-reranker-v2-m3` (potente, mejor con GPU). Contra: engorda la imagen y consume memoria.
- **API hospedada:** `Cohere Rerank` (multilingüe, calidad alta, 3 líneas de integración). Contra: **cuesta dinero por consulta** y **los documentos viajan a un tercero** (con datos de clientes, hay que hablarlo).

> **Recomendación:** sistema interno + español + datos sensibles → **cross-encoder ligero en local.** Saltar a API solo cuando el local se quede corto *de forma medible.*

## Código (lo esencial)

```python
# app/generation/rag/retrieval/reranker.py
class Reranker:
    def __init__(self, model_name: str | None = None) -> None:
        self._model = CrossEncoder(model_name or settings.reranker_model_name)  # se carga UNA vez

    def rerank(self, query: str, candidates: list[RetrievedChunk], top_k: int = 5) -> list[RetrievedChunk]:
        if not candidates:
            return []
        pairs = [(query, c.content) for c in candidates]
        scores = self._model.predict(pairs)
        ranked = sorted(zip(candidates, scores), key=lambda i: i[1], reverse=True)
        return [c for c, _ in ranked[:top_k]]
```

Tres decisiones de producción:
1. **Cargar el modelo una sola vez** al arrancar (tarda segundos). El healthcheck debe esperar a que esté cargado.
2. **Entra lista de chunks, sale lista de chunks** (más corta y mejor ordenada). Eso lo hace una etapa **opcional**: encenderla es un booleano → compararla es un experimento, no una refactorización.
3. **Loguear tamaños de entrada/salida.** Cuando dentro de meses una estimación salga mal, el log por etapa es diagnosticar en minutos vs días.

> **Trampa de concurrencia:** la búsqueda vectorial es asíncrona (espera a la BD); el reranking **no** (es cálculo puro). Una ejecución de cientos de ms **bloquea todas las demás peticiones**. Si hay concurrencia real, despáchalo a un hilo con `asyncio.to_thread`.

## Cuándo NO rerankear

- **El orden vectorial ya es bueno** (corpus pequeño y diferenciado): reordenar lo ya ordenado = coste sin beneficio.
- **El problema es de recall** (los relevantes ni entran en el top-50): es fallo de chunking/embeddings, no de orden. **El reranking no rescata lo que no se recuperó.**
- **No hay presupuesto de latencia.**

> **Señal de que el reranking SÍ toca:** los relevantes **están** entre los candidatos **pero no arriba**. (El caso del e-commerce enterrado bajo la app de pagos.)

---

# Parte 2 — ¿Compensa? Medir la relevancia a mano

## El problema

Añades reranking, lanzas 3 consultas, "tienen mejor pinta", cierras. Dos semanas después: "¿por qué cada estimación tarda medio segundo más?". Respondes "mejoró la recuperación". Y la pregunta inevitable es **¿cuánto?** — que "parece que va mejor" no sobrevive.

**Meta:** convertir "parece mejor" en **"la precisión subió de 0,48 a 0,80 a cambio de 250 ms"**. No hace falta framework ni equipo de datos: una tarde, criterio y una hoja de cálculo. Eso es **medición artesanal**: pequeña, manual, suficiente para la decisión que tienes delante.

## Por qué la intuición engaña

- **Pruebas con las consultas fáciles** (las que tú formularías bien). Los usuarios reales escriben vago y mezclan temas.
- **Recuerdas lo memorable, no lo típico:** un rescate espectacular te marca aunque en el resto nada cambie.
- **Comparas contra una vara que se mueve:** evaluar a ojo el martes vs el jueves mete ruido.

Solución a los tres: **fija de antemano un conjunto de consultas con sus respuestas correctas y mide TODAS las configuraciones contra él.** Ese conjunto es el **golden set**.

## El golden set

> **Golden set** = colección pequeña de **consultas reales**, cada una **anotada a mano** con los documentos que de verdad son relevantes. Es la "verdad de referencia" (*ground truth*).
> **Ground truth** = la respuesta correcta acordada de antemano, contra la que comparas.

Tres decisiones (ninguna es técnica):
1. **Qué consultas:** cubre el uso real, no el cómodo. 2-3 frecuentes, un par de difíciles (e-commerce/pagos), al menos una con términos exactos, alguna larga y desordenada (como las transcripciones).
2. **Cuántas: entre 5 y 20** bien elegidas. *5 representativas valen más que 50 inventadas.* Empieza pequeño.
3. **Quién anota:** quien usaría el resultado (el estimador). Escribe el criterio en una frase **antes** de empezar ("relevante = serviría de referencia directa de esfuerzo"). **Anota en binario** (relevante / no relevante): menos expresivo pero consistente.

## Precision@k

> **precision@k** = (documentos relevantes entre los k devueltos) / k. Mide la calidad de los *k* primeros, que son justo los que llegan al LLM.

Ejemplo: el golden set marca 4 relevantes; el sistema devuelve su top-5; 3 de esos 5 son relevantes → **precision@5 = 3/5 = 0,60**. Se promedia sobre todas las consultas. La alternativa (con reranking) se mide contra **el mismo golden set** y se comparan promedios.

Dos matices:
- **La k de la métrica = la k del sistema.** Si pasas 5 al LLM, mide precision@5 (no @10).
- **Recall@k** como complemento (*"de lo que valía, ¿cuánto trajiste?"*): si anotaste *todos* los relevantes, sale gratis y detecta el documento valioso que no aparece. Métricas que premian el orden fino (**MRR**, **nDCG**) existen, pero para decidir si una técnica entra, **precisión + recall sobre tus k reales sobran.**

## La otra columna: latencia

- **Mide en caliente:** descarta la primera consulta tras arrancar (paga costes fijos: cargar modelos, cachés frías).
- **Usa la MEDIANA, no la media:** 3-5 ejecuciones por consulta; la mediana aguanta el pico atípico.

> **Mediana** = el valor del medio al ordenar las medidas. Más robusta que la media cuando hay pocos datos y algún pico raro.

El arnés de medición vive en `scripts/`, **no** en la aplicación: es una herramienta de decisión puntual, no necesita endpoint ni tests. El **golden set es un archivo versionado** — cambiarlo pasa por revisión, porque cambiar la vara cambia el significado de todas las medidas anteriores.

```python
# scripts/measure_retrieval.py (esencia)
def precision_at_k(retrieved_ids, relevant_ids, k=5):
    top = retrieved_ids[:k]
    return sum(1 for x in top if x in relevant_ids) / len(top) if top else 0.0
# Por consulta: 3 ejecuciones cronometradas + precision_at_k. Al final: media de precisión + mediana de latencia.
```

## La decisión: ganancia vs coste

| Configuración | precision@5 | Latencia mediana |
|---|---|---|
| Vectorial sola | 0,48 | 35 ms |
| Vectorial + reranking | 0,80 | 290 ms |

- **Lectura ingenua:** "el reranking multiplica la latencia por 8" (cierto pero irrelevante).
- **Lectura correcta:** el denominador es **el presupuesto de latencia de toda la experiencia.** Después de recuperar viene la generación del LLM (varios segundos), así que +255 ms es **<5%** del total, y a cambio 2 de cada 5 documentos pasan de ruido a señal → **activar**.
- **El mismo número, decisión opuesta:** en un autocompletado de 300 ms, esos +255 ms son el **85%** → descartar.

> **Una técnica no es buena ni mala; es cara o barata *respecto a un presupuesto*, y el presupuesto lo fija el PRODUCTO, no el pipeline.**

**Cuadrante de decisión** (ganancia vs coste): *activar sin dudar* (mucha ganancia, poco coste) · *evaluar contra presupuesto* (mucha ganancia, mucho coste) · *descartar* (poca ganancia, mucho coste). La zona traicionera: **poca ganancia + poco coste** — la tentación de activar "porque algo suma y apenas cuesta". Pero el coste real no es solo latencia: es un modelo más que operar, una dependencia más que actualizar, un modo de fallo nuevo que depurar a las 3 de la mañana. **Una mejora de 0,02 no paga ese peaje.**

## Lo que esta medición NO te da

- **Sin potencia estadística** con 10 consultas: una diferencia de 0,05 puede ser ruido. Decide con saltos **grandes y consistentes** (0,48 → 0,80), no con décimas.
- **Arrastra el sesgo del anotador** (suficiente para decidir, no verdad universal).
- **Se detiene en la recuperación:** dice qué documentos llegan al LLM, no qué hace el LLM con ellos. Evaluar la generación es otra disciplina, más adelante.

---

# Parte 3 — Búsqueda híbrida: significado + palabras exactas

## El problema

Proyecto: "integración de pagos con **Stripe**, suscripciones y webhooks". El buscador trae proyectos del campo correcto (pasarelas, cobros recurrentes)... pero el presupuesto que integró **exactamente Stripe** (oro puro: tiene el esfuerzo real de pelearse con esa API) aparece en la **posición 14**.

¿Por qué? Para los embeddings, "Stripe" ≈ "pasarela de pago". Esa generalización es su virtud, pero aquí el **nombre propio exacto se diluye** en un vector que promedia todo el chunk.

> **La búsqueda semántica no ve lo literal.** Solución: **no elegir.** Ejecutar las dos búsquedas y fusionarlas.

## Dos familias, dos puntos ciegos

> **Búsqueda léxica (sparse / por palabras clave)** = busca términos literales, pesando los raros más que los comunes. Tecnología clásica: **BM25 / TF-IDF / IDF** (fórmulas que dan más peso a palabras poco frecuentes).
> **Búsqueda semántica (dense / vectorial)** = busca por significado con embeddings.

| | Léxica (palabras) | Semántica (significado) |
|---|---|---|
| Ve bien | Identificadores exactos: "Stripe", "SAP", "ISO 27001" | Sinónimos y paráfrasis: "backoffice" ≈ "panel de administración" |
| Punto ciego | No entiende paráfrasis | Diluye lo literal (nombres, siglas, códigos) |

En estimación conviven los dos tipos de consulta, a menudo en la misma frase. **La conclusión es dejar de elegir.**

## Full-text en PostgreSQL (ya lo tienes)

El instinto dice "Elasticsearch". Resístelo: si los vectores ya viven en PostgreSQL, su motor full-text es maduro → **cero infraestructura nueva.** Piezas:

> **`tsvector`** = el texto ya preprocesado para buscar: en minúsculas, sin "stopwords" (palabras vacías como "de", "la"), y con cada palabra reducida a su raíz.
> **Stemming** = reducir a la raíz: "integraciones"/"integración"/"integrar" → una sola forma. Depende del idioma → usar config `'spanish'`. Lo que el diccionario no reconoce ("Stripe", "webhook") pasa casi intacto — justo lo que queremos.
> **`tsquery`** = la consulta preprocesada igual. `websearch_to_tsquery` acepta sintaxis natural de buscador.
> **Operador `@@`** = comprueba si un `tsvector` satisface una `tsquery`.
> **Índice GIN** = índice invertido (de término → documentos que lo contienen) que hace la búsqueda léxica rápida.
> **`ts_rank`** = la nota de relevancia léxica (por frecuencia y proximidad de términos).

```sql
-- Columna que PostgreSQL mantiene sola, sin triggers
ALTER TABLE budget_chunks
  ADD COLUMN content_tsv tsvector GENERATED ALWAYS AS (to_tsvector('spanish', content)) STORED;
CREATE INDEX ix_budget_chunks_content_tsv ON budget_chunks USING gin (content_tsv);

SELECT chunk_id, ts_rank(content_tsv, query) AS lexical_rank
FROM budget_chunks, websearch_to_tsquery('spanish', :query_text) AS query
WHERE content_tsv @@ query
ORDER BY lexical_rank DESC LIMIT 50;
```

Dos honestidades: `ts_rank` **no es BM25** (no normaliza por longitud igual de fino; hay extensiones con BM25, pero para decenas de miles de chunks la diferencia es ruido frente a *tener* rama léxica). Y Elasticsearch sigue teniendo sentido para corpus enormes — pero no añadas un segundo almacén hasta que el primero se quede pequeño.

## Fusionar dos rankings que no hablan igual

Las dos notas **no son comparables** (la coseno vive en un rango, `ts_rank` en otro). Sumarlas es "sumar metros con kilos". **Normalizar y pesar** (con un parámetro *alpha*) funciona en la demo y se rompe en producción: la distribución de notas cambia con cada consulta, y la calibración de ayer queda mal hoy.

**Solución elegante: ignorar las notas y usar solo las posiciones.**

## Reciprocal Rank Fusion (RRF)

> **RRF** = a cada documento le das, en cada ranking donde aparece, una puntuación que depende solo de su **posición** (mejor posición = más puntos), y sumas.

```
rrf_score(d) = Σ  1 / (k + rank_i(d))
```
donde `rank_i(d)` = posición de *d* en el ranking *i* (empezando en 1), y `k` = constante de suavizado (**típicamente 60**).

Ejemplo (k=60): doc **2.º en semántica y 5.º en léxica** → 1/62 + 1/65 ≈ **0,0315**. Doc **1.º en semántica pero ausente en léxica** → 1/61 ≈ **0,0164**. **El que ambas búsquedas consideran bueno gana al campeón de una sola.**

> **RRF premia el consenso:** aparecer razonablemente arriba en varios rankings vale más que arrasar en uno. Para el presupuesto de Stripe es el rescate exacto: la léxica lo sube por el término, la semántica lo sostiene por el tema, la fusión lo coloca arriba.

**`k` es el único mando:** pequeña → mandan los primeros puestos; grande → fusión más "democrática". El **60** viene del paper original y es robusto. **Tocarlo es optimización prematura.**

```python
# app/generation/rag/retrieval/fusion.py
def reciprocal_rank_fusion(rankings: list[list[str]], k: int = 60) -> list[str]:
    scores = defaultdict(float)
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] += 1.0 / (k + rank)
    return [cid for cid, _ in sorted(scores.items(), key=lambda i: i[1], reverse=True)]
```

Recibe **una lista de rankings, no exactamente dos** — a RRF le da igual cuántas fuentes fusiona. Por eso sirve también para multi-query o multi-índice **sin cambiar una línea.**

## Cuándo gana

Las dos ramas se lanzan **en paralelo** (`asyncio.gather`) → la latencia es la de la rama más lenta, no la suma. El contrato es el mismo de siempre (consulta → lista de chunks), así que cambiar vectorial por híbrida es cambiar una pieza tras una config.

- **Gana claro:** consultas con identificadores exactos (tecnologías, productos, siglas, normas) y consultas cortas y específicas.
- **Apenas mueve la aguja:** consultas puramente conceptuales y bien parafraseadas (la semántica ya iba bien). RRF **degrada con elegancia**: si ambos rankings coinciden, el fusionado también.
- **Vigilar:** idiomas mezclados (español con términos en inglés) — el `tsvector` español no hace stemming del inglés. No suele ser grave (los términos ingleses funcionan como identificadores exactos), pero explica resultados raros.

---

# Parte 4 — Expansión y descomposición de consultas

## El problema: la consulta también falla

Hasta aquí todo mejoraba **después** de la consulta (índices, rankings, filtros). Pero a veces el problema es **la consulta misma**. Dos casos distintos (y **no intercambiables**):

- **Consulta multi-tema:** la entrada real no es limpia, es una transcripción de 40 min donde el cliente salta de catálogo a app móvil a facturación. Su embedding es el **promedio de todos esos temas** → "un vector cerca de todo y de nada", que devuelve "proyectos grandes con muchas cosas" — lo peor para estimar (que se hace **por partidas**).
- **Lotería de la formulación:** mismo concepto, palabras distintas. El cliente dice "que los comerciales vean sus números desde el móvil"; el presupuesto relevante decía "dashboard de KPIs responsive". Los embeddings cruzan paráfrasis mejor que nada, pero no son inmunes: la formulación concreta decide los vecinos. Que la recuperación dependa de la suerte al redactar es inaceptable.

## Dos técnicas que parecen una

> **Expansión (multi-query)** = generar varias **paráfrasis** de la *misma* intención. Combate la lotería de la formulación.
> **Descomposición** = partir una consulta de *varios* temas en **sub-consultas**, una por tema. Combate el embedding promediado.

| | Expansión | Descomposición |
|---|---|---|
| Cuándo | 1 intención, muchas formas de decirla | varias intenciones mezcladas |
| Genera | N paráfrasis | N sub-consultas (una por tema) |
| Ejemplo | "comerciales ven números en móvil" → "dashboard métricas comerciales móvil" / "KPIs ventas en app" | la transcripción → "catálogo con inventario" / "app móvil clientes" / "integración facturación" |
| Cómo fusionar | **premiar consenso** (RRF) | **garantizar cobertura por tema** (round-robin) |

> **Regla en una línea:** ¿la consulta pide UNA cosa que puede decirse de muchas maneras, o MUCHAS cosas a la vez? → expandir / descomponer. **Aplicar la equivocada no es neutro.**

## Generar las variantes: un LLM con correa corta

Lo moderno es usar un LLM (antes: diccionarios de sinónimos). Pero "llamar al LLM sin más" es la versión ingenua. Dos disciplinas:

1. **Salida estructurada, no texto libre.** Las sub-consultas alimentan la siguiente etapa; parsearlas con regex es fabricar un punto de rotura. Defínelas como esquema y exige que se cumpla:

```python
class SubQuery(BaseModel):
    topic: str = Field(description="Etiqueta corta de partida, p.ej. 'facturación'")
    query: str = Field(description="Consulta autónoma para esa partida")

class QueryDecomposition(BaseModel):
    sub_queries: list[SubQuery] = Field(min_length=1, max_length=4)
```

2. **Instrucciones que ACOTAN, no que inspiran.** El riesgo es que el LLM "mejore" demasiado: invente requisitos, traduzca la jerga a sinónimos genéricos, fabrique 8 sub-consultas donde había 2 temas. Cada creatividad contamina la búsqueda:

```text
- Como mucho 4 sub-consultas. Pocas es mejor que fragmentado.
- Cada una autónoma y entendible sin las demás.
- Conserva los términos exactos del dominio (productos, tecnologías, siglas). Nunca los cambies por sinónimos genéricos.
- Nunca añadas requisitos que la descripción no menciona.
- Si solo hay un tema, devuelve UNA sub-consulta que lo reformule limpio.
```

Dos detalles que son decisiones: el **límite de 4 vive en dos sitios** — el esquema (`max_length=4`, que el modelo *no puede* violar) y la instrucción (que explica el porqué); quieres los dos. Y el **modelo se elige por configuración**: no el más capaz, sino el más rápido que haga bien una tarea pequeña (esta llamada está en el camino crítico).

## Fusionar según para qué buscabas

Sutileza que casi todo el material introductorio se salta: **expansión y descomposición NO se fusionan igual.**

- **Expansión → RRF (consenso).** Las N variantes buscaban lo mismo; estar bien en varias es señal fuerte.
- **Descomposición → cobertura por tema (round-robin).** Las N sub-consultas buscaban cosas distintas a propósito. Premiar el consenso aquí **sabotea el objetivo**: un presupuesto de catálogo jamás saldrá en el ranking de facturación, y el tema con más presupuestos inundaría el resultado.

> **Round-robin** = ir cogiendo por turnos el mejor de cada ranking (1º de A, 1º de B, 2º de A, 2º de B...), para que cada tema traiga sus referencias.

```python
def interleave_rankings(rankings, top_k):
    """Round-robin entre rankings para garantizar cobertura por tema."""
    fused, seen = [], set()
    for position in range(max(len(r) for r in rankings)):
        for ranking in rankings:
            if position < len(ranking) and ranking[position].id not in seen:
                fused.append(ranking[position]); seen.add(ranking[position].id)
                if len(fused) == top_k:
                    return fused
    return fused
```

La **deduplicación** (`seen`) no es opcional: un presupuesto que cubre dos temas aparece en dos rankings y, sin deduplicar, ocuparía dos plazas del contexto contando como una sola información. Las N búsquedas van **en paralelo** → buscar 4 veces cuesta casi lo que buscar 1.

## El precio y cuándo NO aplicar

Coste **distinto a todo lo anterior**: meten una llamada al LLM en el camino crítico, **antes** de empezar a buscar.
- **Latencia:** ~200 ms–1 s (modelo pequeño). El sumando más caro, y llega el primero.
- **Tokens:** poco por consulta, pero × cada consulta del sistema.
- **Carga:** N búsquedas = N consultas a la BD.

Mitigaciones: (1) el **modelo más pequeño** que sea fiable *—verificándolo con ejemplos reales—*; (2) **limitar a 3-4 variantes** (la quinta aporta ≈0); (3) **cachear reformulaciones** (la misma consulta no se repiensa). Y la mayor: **no aplicar la técnica cuando no toca** — una consulta corta, nítida y de un solo tema no se reformula.

**Árbol de decisión:** ¿varios temas? → SÍ: **descomposición**. → NO: ¿formulación nítida con vocabulario del dominio? → SÍ: **búsqueda directa** (coste cero) · NO: **expansión**. La decisión queda **en los logs** para auditar. *Aviso de medición:* estas técnicas brillan en las consultas difíciles, así que si tu golden set solo tiene consultas de laboratorio, parecerán peores de lo que son.

---

# Parte 5 — Multi-índice y routing

## El problema: corpus que engorda y se mezcla

El sistema ya guarda tres familias muy distintas: **presupuestos** (estructurados, partidas y cifras), **transcripciones** (lenguaje oral, divagante) y **documentación técnica** (densa). Ante "¿cuánto costó la integración con **SAP**?", el documento que responde es un **presupuesto**, pero en un índice único el top-5 viene contaminado: dos transcripciones donde alguien *habló* de SAP, un fragmento de doc técnica, y solo después los presupuestos.

> El índice único responde a "¿qué se parece a esta consulta?" cuando la pregunta era **"¿qué *presupuesto* se parece a esta consulta?"**.

Por qué se degrada el índice mezclado: cada familia tiene **textura distinta** (una transcripción puede quedar cerca por verbosa, no por útil); el **tipo más numeroso inunda** (10× más transcripciones → el top-k tendrá la proporción del volumen, no de la utilidad); cada familia quiere **su propio preprocesamiento**; y **operar duele** (reindexar transcripciones no debería tocar presupuestos). Respuesta: **particionar** en colecciones separadas.

## Cómo particionar en PostgreSQL

> **(A) Columna discriminadora** = una sola tabla con una columna `document_type` que dice de qué familia es cada fila.
> **(B) Tabla por familia** = una tabla distinta para cada tipo (`budget_chunks`, `transcript_chunks`...).

| Criterio | (A) Columna | (B) Tablas separadas |
|---|---|---|
| Esquemas que divergen (importes vs interlocutores) | ❌ columnas NULL por familia | ✅ esquema a medida |
| Volúmenes muy distintos | ⚠️ índices parciales | ✅ un índice por población homogénea |
| Independencia operativa | ❌ todo cambio es global | ✅ operaciones locales |
| Búsqueda cruzada frecuente | ✅ una consulta con `WHERE` | ❌ N consultas + combinar |
| Fricción inicial | ✅ una migración trivial | ❌ 3 tablas, 3 ingestas, 3 índices |

> **Regla:** si los metadatos **divergen** → tablas separadas; si las familias son **variaciones de lo mismo** → columna discriminadora. Cuando te ves añadiendo `speaker_count` (NULL en todos los presupuestos), la tabla única te está diciendo que son entidades distintas conviviendo a disgusto.

En estimación los esquemas divergen claro → **Opción B.** El precio se paga en mantenimiento (3 migraciones, 3 índices), no en rendimiento.

## El router: jerarquía de coste creciente

> **Router** = el componente que decide en qué colección(es) buscar cada consulta.

Recorre **de menor a mayor coste**, usando lo caro solo para lo que lo barato no resuelve:

- **Nivel 0 — el mejor router es no tener router.** Muchas consultas ya traen su destino implícito: el flujo de estimación **busca presupuestos siempre.** Captúralo en el **contrato de la API** (parámetro de colección o endpoints distintos): gratis y determinista. *Pregunta antes de construir nada: ¿de verdad el servicio IA tiene que adivinar algo que el backend ya sabe?*
- **Nivel 1 — reglas deterministas.** Para consultas sin destino (buscador libre interno). Patrones inequívocos: "¿cuánto costó...?" → presupuestos; "¿qué dijo el cliente...?" → transcripciones. Frágiles pero gratis y transparentes.
- **Nivel 2 — el LLM como clasificador.** Para lo que las reglas no resuelven: modelo pequeño con salida estructurada.

```python
class SearchTarget(StrEnum):
    BUDGETS = "budgets"; TRANSCRIPTS = "transcripts"; TECHNICAL_DOCS = "technical_docs"

class RoutingDecision(BaseModel):
    targets: list[SearchTarget] = Field(min_length=1, max_length=3,
        description="Colecciones a buscar. Varias solo si la consulta lo necesita de verdad")
    reason: str = Field(description="Una frase corta explicando la elección")
```

Tres decisiones: (1) la salida es una **lista de destinos, no un destino con un nivel de confianza** — cuando el clasificador duda entre dos colecciones, lo correcto es buscar en ambas, no elegir mal con un 0,55. (2) El campo **`reason` hace cada decisión auditable** y cuesta una frase. (3) El **`StrEnum` cierra el universo** (`StrEnum` = enumeración fija de valores válidos): el modelo no puede inventarse una colección que no existe.

- **Nivel 3 — buscar en todo.** Si ni el clasificador decide, **buscar en paralelo en todas y combinar**: el fallback honesto. **Degradación elegante: en el peor caso se comporta como el índice único, nunca peor.**

## Combinar colecciones (y la procedencia como dato)

Las notas de colecciones distintas **no son comparables** (cada una con su textura) — versión agravada del problema de la híbrida. Salidas sensatas: (1) si necesitas un ranking único, **fusión por posiciones o por cuotas** (los 2 mejores de cada una), **nunca por nota cruda**; (2) muchas veces lo correcto es **no fusionar** y presentar agrupado por origen ("esto dicen los presupuestos; esto se habló en reuniones"). Para todo ello, **cada chunk viaja con su etiqueta de procedencia** — perderla en la fusión es perderla para siempre.

*Apunte:* un componente que examina una petición y la manda al especialista adecuado es un **patrón de delegación** — el embrión de cómo los sistemas con agentes se reparten el trabajo. La diferencia es de grado: nuestro router hace **una** clasificación acotada, sin razonamiento abierto ni herramientas. Esa contención es deliberada.

## Cuándo NO particionar

Tentador de ignorar porque particionar *parece* arquitectura seria. **No particiones si:** el corpus es funcionalmente homogéneo; una colección concentraría el **95%** de las consultas (el router sería un peaje que casi siempre da la misma respuesta); o es "para cuando crezcamos". **La señal legítima es observable:** resultados de una familia contaminando consultas de otra, de forma recurrente y medible (el caso de SAP no es hipotético).

---

# Parte 6 — Filtrado temporal/contextual, y el orden del pipeline

## El punto ciego de la similitud

Proyecto: portal de cliente con área privada, gestión documental y firma electrónica. La búsqueda encuentra un presupuesto casi calcado → similitud altísima, primera posición indiscutible. **Pero es de 2019:** frontend en AngularJS (obsoleto), proveedor de firma que ya no existe, tarifas viejas. Como referencia de "qué partidas tiene", orienta; como referencia de "cuánto cuesta hoy", es **peligroso** — y el LLM no tiene forma de saberlo.

> **El embedding codifica lo que el texto *dice*, no *cuándo* se escribió, ni *con qué tecnología*, ni *si sigue siendo verdad*.** Esas dimensiones viven en los **metadatos**. Bien usados son la técnica con mejor relación coste-beneficio: la única cuyo coste es *negativo*, porque **filtrar antes de buscar abarata todo lo que viene después.**

## Filtros duros: recortar el universo antes de buscar

> **Filtro duro** = una condición sobre metadatos que **excluye** documentos antes de que la similitud opine. (Proyecto React Native → fuera las tecnologías sin relación; política de no usar referencias de >4 años → la fecha corta en seco.)

```sql
SELECT chunk_id, embedding <=> :query_embedding AS distance
FROM budget_chunks
WHERE project_date >= :min_project_date
  AND technology = ANY(:relevant_technologies)
ORDER BY distance LIMIT 50;
```

> **LA TRAMPA (crítica):** los índices vectoriales aproximados como **HNSW no entienden de `WHERE`.**
> **HNSW** = el tipo de índice que hace la búsqueda vectorial rápida navegando un grafo de vecinos. El problema: busca los vecinos más cercanos del **universo completo** y el filtro se aplica **después**. Si pides 50 con un filtro que solo cumple el 5% del corpus, el índice devuelve sus 50 vecinos, el filtro descarta 48, y la consulta entrega **2 resultados — o cero — sin ningún error visible.**

Soluciones:
- **Escaneo iterativo** (`hnsw.iterative_scan`, pgvector ≥ 0.8): sigue pidiendo candidatos hasta reunir los que pediste *tras* el filtro.
- **Índice parcial:** un HNSW construido solo sobre las filas que cumplen la condición (para filtros muy frecuentes y selectivos).
- **El hábito de fondo:** cuando combines filtros con búsqueda aproximada, **verifica cuántos resultados vuelven y déjalo en los logs.** "El filtro vació el resultado en silencio" es de los fallos más desconcertantes de depurar.

**Segunda condición:** los metadatos tienen que **existir y estar bien.** La fecha viene gratis; tecnología, sector o tamaño de equipo hay que extraerlos en la ingesta (con reglas o con un LLM de extracción), **una vez por documento, nunca por consulta.** *La calidad de la extracción es el techo de todo:* un filtro duro sobre un metadato mal extraído **es peor que ningún filtro**, porque excluye con total confianza al mejor candidato y nadie ve el hueco. **Regla: filtros duros solo para metadatos en los que confías; lo dudoso, como mucho, pondera.**

## El tiempo: el metadato que nunca sobra

Su efecto es universal y direccional: lo reciente vale más (precios caducan, stacks rotan). Dos formas:

- **Ventana dura** (solo los últimos N años): fácil de explicar pero **brutal en el borde** — el de hace 3 años 11 meses compite igual, el de hace 4 años 1 mes no existe. Peligroso si el corpus es escaso (puede dejar fuera la única referencia decente de un tipo raro).
- **Decaimiento continuo** (la edad como penalización progresiva, no veredicto). Forma habitual: exponencial.

> **Semivida (half-life)** = cada cuántos días un presupuesto pierde **la mitad** de su peso. Es el único parámetro, y tiene lectura directa de negocio.

```python
# app/generation/rag/retrieval/temporal.py
def temporal_weight(document_date: date, half_life_days: int = 900) -> float:
    """Decaimiento exponencial: pierde la mitad del peso cada semivida."""
    age_days = (date.today() - document_date).days
    return 0.5 ** (max(age_days, 0) / half_life_days)   # max(...,0) evita pesos > 1 con fechas futuras
```

Con semivida 900 días (≈ 2,5 años): **1 año → ≈76%**, **2,5 años → 50%**, **2019 → ≈15%.** El presupuesto de 2019 sigue apareciendo (degradado, si es la única referencia de su especie), pero ya no le gana la primera posición a un equivalente reciente. **La semivida no se optimiza con una fórmula:** se elige con juicio ("¿a partir de cuándo dejarías de fiarte de las cifras?") y se revisa si el dominio cambia.

**Ventana vs decaimiento no es ideológico:** ventana cuando hay **razón categórica** (compliance, política de empresa, un cambio de era); decaimiento para la **erosión gradual normal.** Se combinan: ventana generosa como red de seguridad + decaimiento dentro como orden fino.

## Ponderación dinámica (contextual) y su peligro

> **Ponderación dinámica** = que la **importancia de cada metadato dependa de la consulta.** Si la descripción gira sobre una tecnología, la coincidencia tecnológica pesa mucho; si es para banca, sube la experiencia sectorial; si no menciona nada, esos metadatos callan. Se implementa como **multiplicadores sobre el orden final**, definidos **en configuración, no escondidos en el código.**

> **La advertencia más seria de la sesión:** aquí el exceso de ingeniería acecha mejor disfrazado. **Cada peso es un número mágico que alguien tendrá que justificar, recalibrar y depurar.** Un sistema con siete *boosts* contextuales interactuando es uno donde nadie sabe ya por qué un documento quedó tercero — has cambiado la opacidad del embedding por una **opacidad artesanal, peor porque encima parece controlable.**

Progresión sensata: **primero** filtros duros + decaimiento temporal (resuelven la mayor parte con dos decisiones explicables); **después** ponderación dinámica, solo para metadatos con *evidencia medida* de que aporta. **Test de humildad: si no puedes explicar en una frase por qué un boost vale 1,3 y no 1,5, no estaba listo para producción.**

## Ensamblar el pipeline: el orden importa

> **El principio en una línea: lo barato y excluyente, al principio; lo caro y fino, al final; lo blando, al cierre.**

```
Consulta
  ▼  Reformulación (expansión/descomposición)  ─┐ operan sobre la consulta:
  ▼  Routing (a la colección adecuada)          ─┘ deciden QUÉ y DÓNDE se busca
  ▼  Filtros duros (tecnología, fecha)           ── lo excluyente, TEMPRANO (cada doc fuera es trabajo que nadie hará)
  ▼  Búsqueda híbrida (semántica + léxica, en paralelo)
  ▼  Fusión RRF (consenso de posiciones)         ── conjunto amplio de candidatos
  ▼  Reranking (cross-encoder)                   ── lo caro, TARDE, solo sobre los supervivientes
  ▼  Ponderación (temporal, contextual)          ── lo blando, AL CIERRE, sobre los finalistas
  ▼
 Top-5 al generador

Embudo:  corpus (~miles) ─► filtrado ─► top-50 ─► 5 finalistas
```

**La asimetría es deliberada:** los filtros duros van lo **antes posible** (ahorran trabajo a todo lo que sigue); las ponderaciones blandas, lo **más tarde posible** (ajustan sobre el conjunto pequeño donde equivocarse es barato). Los dos errores clásicos: **rerankear documentos que un filtro iba a tirar** (dinero quemado) y **ponderar tan pronto que el ajuste blando expulsa candidatos antes de que el reranker los valore** (información destruida).

**Cada etapa se enciende por configuración:** el pipeline completo es el **camino máximo, no el obligatorio.** La consulta simple no paga el peaje de la compleja, y poder encender/apagar cada pieza es la única forma de responder con datos a "¿qué aportas y cuánto cuestas?".

---

# Chuleta de una página

| Técnica | Qué resuelve | Cuándo SÍ | Cuándo NO | Coste |
|---|---|---|---|---|
| **Reranking** (cross-encoder) | El orden del top-k no es fiable | Relevantes *están* pero no arriba | Recall pobre; orden ya bueno; latencia justa | ~100–300 ms en el camino crítico |
| **Híbrida** (semántica + léxica + RRF) | La semántica diluye términos literales | Identificadores exactos, consultas cortas | Consultas puramente conceptuales | 1 SQL extra + columna `tsvector` + índice GIN |
| **Expansión** (multi-query) | Lotería de la formulación (1 intención) | Formulación poco nítida | Consulta corta y nítida | 1 llamada LLM (~0,2–1 s) antes de buscar |
| **Descomposición** | Embedding promediado (varias intenciones) | Transcripciones, multi-tema | Consulta de un solo tema | 1 llamada LLM + N búsquedas |
| **Multi-índice + routing** | Corpus heterogéneo contamina | Contaminación recurrente y medible | Corpus homogéneo; 95% a una colección; "para crecer" | Mantenimiento (N tablas/índices) |
| **Filtro duro** (metadatos) | Similitud ignora tecnología/fecha | Metadatos en los que confías | Metadato dudoso o mal extraído | ≈ negativo (abarata el resto) — ojo a la trampa de HNSW |
| **Decaimiento temporal** | Lo viejo parece igual de relevante | Erosión gradual (precios, stacks) | (combínalo con ventana si hay razón categórica) | 1 multiplicador; elegir semivida con juicio |
| **Ponderación dinámica** | Metadatos importan según la consulta | Solo con evidencia medida | Por defecto (riesgo de "opacidad artesanal") | Números mágicos que justificar |

**Fórmulas:**
- `precision@k = (relevantes en top-k) / k` · promediar sobre el golden set; latencia como **mediana** (en caliente).
- `rrf_score(d) = Σ 1 / (k + rank_i(d))`, k ≈ 60 (solo posiciones, nunca notas).
- `temporal_weight = 0.5 ** (age_days / half_life_days)`, semivida ≈ 900 días → 50%.

**Orden del pipeline:** reformulación → routing → **filtro duro** → híbrida → fusión RRF → **reranking** → **ponderación blanda** → top-5. *(Lo excluyente temprano; lo caro al final; lo blando al cierre.)*

**La meta-lección:** ninguna técnica se añade por moda. Cada incorporación se decide contra una tabla de dos columnas — **cuánto gana** (precision@k sobre el golden set) y **cuánto cuesta** (latencia mediana, como fracción del presupuesto que fija el producto).

---

## Cómo conecta con nuestro ejercicio

- **Ya tenemos pgvector** (Sesión 8) sobre un **único Postgres.** La rama léxica (`tsvector` + GIN) y los filtros duros (`WHERE`) caen sobre esa misma base **sin infraestructura nueva** — el argumento de la Parte 3. La trampa HNSW + `WHERE` (Parte 6) aplica tal cual.
- **Corpus pequeño** (~decenas de presupuestos): refuerza dos elecciones — *candidate pool* hacia el extremo bajo (30–50) y **decaimiento temporal** mejor que **ventana dura** (con pocos documentos, una ventana puede dejar un tipo de proyecto sin referencia).
- **Estructura por capas** (`app/generation/rag/retrieval/...` desde la Sesión 7): reranker, fusión, reformulación, router y filtrado temporal encajan como **módulos componibles**, cada uno activable por un flag de `settings` — el patrón "etapa = experimento de un booleano".
- **Medición artesanal** (Parte 2): `scripts/measure_retrieval.py` + un `golden_set.json` versionado es el siguiente entregable natural para decidir, con números de nuestro dominio, qué etapas se quedan.
