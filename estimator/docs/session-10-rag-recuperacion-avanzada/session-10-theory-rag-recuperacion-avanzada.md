# Sesión 10 — Teoría: recuperación avanzada (reranking · medición · híbrida · reformulación · routing · filtrado) y el orden del pipeline

> Resumen único de los 6 artículos de teoría de la Sesión 10 (AI Engineering 2026).
> Hilo conductor: el **sistema de estimación de proyectos** — buscar entre presupuestos históricos para estimar uno nuevo.
> La Sesión 9 montó el RAG básico (query → retrieval → augmentation → generation). La Sesión 10 va de **hacer que el retrieval sea de verdad bueno**.

---

## 0. La idea en una página (para cualquiera)

Imagina un archivo enorme de presupuestos de proyectos pasados. Cuando llega un proyecto nuevo, el sistema busca los presupuestos parecidos para usarlos como referencia. En la Sesión 9 ese buscador funcionaba con una sola técnica: convertir cada texto en una lista de números (un "embedding") y traer los más cercanos. Funciona como primera aproximación, pero falla de seis maneras predecibles:

1. **Encuentra bien, pero ordena mal.** Trae presupuestos relevantes, pero el orden de los primeros es poco fiable — y al modelo solo le pasamos los 5 primeros.
2. **Es miope para lo literal.** "Stripe" se le parece a "pasarela de pago", así que el presupuesto que usó *exactamente* Stripe se diluye entre genéricos.
3. **La pregunta del usuario suele ser mala consulta.** Una transcripción de reunión de 40 minutos que mezcla cinco temas produce una búsqueda "cercana a todo y a nada".
4. **Mezcla churras con merinas.** Si el archivo tiene presupuestos, transcripciones y documentación técnica revueltos, una pregunta sobre costes acaba contaminada con charlas de reunión.
5. **Ignora el tiempo y el contexto.** Un presupuesto de 2019 puede parecer perfecto y ser peligroso (tecnología obsoleta, tarifas viejas). El embedding no sabe *de cuándo* es.
6. **No sabemos si nuestras mejoras mejoran algo.** "Parece que va mejor" no es un argumento.

La Sesión 10 da una herramienta para cada fallo:

| # | Fallo | Técnica | Artículo |
|---|-------|---------|----------|
| 1 | Ordena mal | **Reranking** (segunda pasada que reordena) | 1 |
| 6 | No sabemos si compensa | **Medición artesanal** (golden set + precision@k vs latencia) | 2 |
| 2 | Miope para lo literal | **Búsqueda híbrida** (semántica + palabras clave) | 3 |
| 3 | La consulta es mala | **Expansión y descomposición** de consultas | 4 |
| 4 | Corpus revuelto | **Multi-índice y routing** | 5 |
| 5 | Ignora tiempo/contexto | **Filtrado contextual y temporal** | 6 |

**La meta-lección de toda la sesión** (vale más que cualquier técnica concreta): cada técnica es una **etapa del pipeline activable por configuración y medible**. No se añade nada porque esté de moda; se añade solo cuando una tabla con dos columnas — *cuánto gana* y *cuánto cuesta* — lo justifica. La pregunta que toda pieza debe responder para quedarse: **"¿Qué aportas tú, exactamente, y cuánto cuestas?"**

---

# PARTE 1 — Reranking: cuando el top-k vectorial no es suficiente

## 1.1 El problema, en términos humanos

Llega una transcripción que describe una **plataforma de e-commerce** (catálogo, carrito, inventario, panel de administración). El buscador devuelve, **en primera posición**, un presupuesto de una **app de pagos móviles** de hace dos años.

No es un error absurdo: e-commerce y pagos comparten vocabulario (transacciones, pasarelas, checkout, seguridad). En el espacio vectorial están genuinamente cerca. Pero para estimar un e-commerce ese presupuesto es casi inútil — el grueso del esfuerzo de un e-commerce está en catálogo, inventario y administración, no en la pasarela. Si el LLM genera la estimación con ese contexto, saldrá sesgada.

> **La frase que resume todo:** la búsqueda vectorial es **excelente encontrando candidatos y mediocre ordenándolos**. La solución no es cambiar el modelo de embeddings ni el chunking: es **añadir una segunda etapa que haga bien lo que la primera hace mal** (ordenar).

## 1.2 Por qué el bi-encoder ordena mal

El modelo de embeddings es un **bi-encoder**: codifica cada texto **por separado** y lo comprime en un vector de dimensión fija. La relevancia se *aproxima* midiendo la distancia entre el vector de la consulta y el de cada chunk.

Esa independencia es lo que lo hace **viable en producción**: los documentos se vectorizan una vez en la ingesta, y buscar es barato (vectorizar la consulta + comparar contra vectores precalculados con un índice ANN — *approximate nearest neighbours*). Millones de documentos, milisegundos de búsqueda.

Pero la compresión a un solo vector se paga al ordenar con precisión, por dos motivos:

- **El vector promedia.** Un presupuesto de e-commerce con una sección menor de pagos produce un embedding que mezcla todo su contenido; uno de una app de pagos produce un embedding donde los pagos dominan. Frente a una consulta que menciona pagos de pasada, **ambos quedan a distancias parecidas** — el vector no distingue entre "habla principalmente de esto" y "lo menciona entre otras diez cosas".
- **Consulta y documento nunca se miran.** El bi-encoder codifica cada texto sin saber con qué se va a comparar. No hay ningún punto donde el modelo pueda razonar "esta consulta pide e-commerce y este documento trata de pagos; se parecen, pero no es lo que pide". La similitud coseno es **geometría sobre dos resúmenes comprimidos**, no una lectura conjunta.

Consecuencia práctica: entre los **50 presupuestos más cercanos**, los relevantes casi siempre están — pero **el orden dentro de esos 50 es poco fiable**. Y a un pipeline que pasa 5 documentos al LLM, le va la vida en ese orden.

## 1.3 Bi-encoder vs cross-encoder

| | **Bi-encoder** | **Cross-encoder** |
|---|---|---|
| Entrada | Consulta y documento **por separado** | `Consulta [SEP] Documento` **juntos** |
| Procesa | Dos transformers independientes | Un transformer, **atención cruzada** entre todos los tokens |
| Salida | Un vector por texto → similitud coseno | **Directamente una puntuación de relevancia del par** |
| Precálculo | Sí (vectores en la ingesta) → búsqueda barata | **No** — una inferencia por par, en cada consulta |
| Calidad de orden | Imprecisa | Precisa (gana sistemáticamente en benchmarks de ranking) |

El cross-encoder puede capturar que "plataforma de e-commerce" y "aplicación de pagos" comparten campo semántico pero no intención, porque **ve los dos textos en el mismo contexto de atención** y fue entrenado específicamente para puntuar relevancia de pares. Tiene acceso a información que el bi-encoder destruyó al comprimir.

Su precio: **no hay nada que precalcular**. Puntuar todo un corpus por cada consulta es inviable.

> **El trade-off en una frase:** el cross-encoder es preciso y lento; el bi-encoder es impreciso y rápido. **Ninguno, solo, resuelve el problema.**

## 1.4 Recall-then-rerank: el pipeline de dos etapas

La solución estándar en recuperación de información (anterior a los LLMs — los buscadores web la usan hace décadas): **encadenar ambos modelos**.

1. **Etapa de recall (red amplia, barata).** La búsqueda vectorial recupera un conjunto generoso de candidatos: **top-50**. No se pide orden fino; se pide que los relevantes *estén* en el conjunto. Tarea del bi-encoder. ~10 ms sobre todo el corpus.
2. **Etapa de precisión (reranking).** El cross-encoder puntúa **solo esos 50 pares** y reordena. Nos quedamos con el **top-5**. Como solo evalúa 50 pares (no el corpus), su coste se vuelve asumible. ~100–300 ms con un modelo ligero en CPU.

```
Corpus (miles) ──► Búsqueda vectorial (fast & cheap, ~10ms) ──► Top-50 candidatos
                                                                      │
                              Top-5 ◄── Cross-encoder (slow & precise, ~100-300ms) ◄┘
                                │         (50 inferencias por consulta)
                                ▼
                           Contexto del LLM
```

> **Dos reglas de oro del diagrama:** (1) el reranker **no toca el corpus**: el techo de calidad lo fija lo que entre en el top-50. (2) **El reranking reordena, no recupera.**

## 1.5 Cómo elegir los dos números (no por inercia)

- **Tamaño del conjunto amplio (50) → controla el TECHO de calidad.** Si el presupuesto relevante no entra en el top-50 vectorial, ningún reranker lo rescata. Más candidatos = más margen, pero más latencia (cada candidato es una inferencia más). En corpus pequeños y heterogéneos (como un histórico de presupuestos de empresa), **30–75** suele ser razonable. Diagnóstico rápido: vigilar en qué posición quedaban los relevantes en el ranking vectorial original.
- **Tamaño del conjunto final (5) → lo dicta el consumidor del contexto, no el reranker.** ¿Cuántos presupuestos caben con holgura sin diluir la instrucción? ¿Cuántos aporta de verdad el caso de uso? Dato clave: **5 presupuestos bien elegidos baten a 15 mediocres** — el generador también sufre cuando se entierra la señal en ruido.

## 1.6 El panorama de modelos: local vs hospedado

**Local (open source, `sentence-transformers`):**
- Familia clásica **`ms-marco-MiniLM`** (entrenada sobre MS MARCO, pares consulta-pasaje): pequeños, rápidos en CPU, competentes. **Pero son monolingües en inglés.**
- Para español/multilingüe: **`mmarco-mMiniLMv2`** (multilingüe ligero) o **`BAAI/bge-reranker-v2-m3`** (multilingüe potente, más pesado, idealmente GPU). Clásico equilibrio calidad-latencia.
- A favor: **coste marginal cero por consulta**, los datos no salen de tu infraestructura (con presupuestos de clientes, esto puede ser *requisito*), sin latencia de red. En contra: PyTorch engorda la imagen, el modelo consume memoria permanente, la calidad de los pequeños no es punta de gama.

**Hospedado (API):**
- **`Cohere Rerank`** es la referencia: le envías consulta + documentos, devuelve la lista reordenada con puntuaciones; multilingüe sin configurar; calidad superior a los cross-encoders pequeños; integración en tres líneas. En contra: **coste monetario por consulta**, dependencia de red en el camino crítico, y **los documentos viajan a un tercero** (con información comercial sensible, conviene hablarlo antes).

> **La postura del artículo:** para un sistema interno, corpus en español, volumen moderado y datos sensibles → **cross-encoder multilingüe ligero en local**. Saltar a un reranker hospedado cuando el modelo ligero se quede corto *de forma medible*, o cuando no quieras operar el modelo. Esa decisión se toma con números de tu dominio, no con benchmarks genéricos.

## 1.7 Implementación (lo que diferencia tutorial de producción)

```python
# app/generation/rag/retrieval/reranker.py
from sentence_transformers import CrossEncoder
from app.foundation.config import settings
from app.foundation.logging import get_logger

logger = get_logger(__name__)

class Reranker:
    """Cross-encoder reranker for retrieved candidates."""

    def __init__(self, model_name: str | None = None) -> None:
        self._model_name = model_name or settings.reranker_model_name
        self._model = CrossEncoder(self._model_name)
        logger.info("reranker_loaded", model=self._model_name)

    def rerank(self, query: str, candidates: list[RetrievedChunk], top_k: int = 5) -> list[RetrievedChunk]:
        if not candidates:
            return []
        pairs = [(query, c.content) for c in candidates]
        scores = self._model.predict(pairs)
        ranked = sorted(zip(candidates, scores), key=lambda item: item[1], reverse=True)
        logger.info("rerank_completed", candidates_in=len(candidates), candidates_out=min(top_k, len(ranked)))
        return [c for c, _ in ranked[:top_k]]
```

Tres decisiones de producción:
1. **El modelo se carga una vez, en la construcción** (cargarlo cuesta segundos). Singleton de ciclo de vida compartido entre peticiones — como el cliente del LLM. Consecuencia: arranque más lento y pesado; el *healthcheck* debe esperar a que el modelo esté cargado.
2. **Entra y sale el mismo tipo** (lista de chunks → lista de chunks más corta y mejor ordenada). Esto lo hace una **etapa opcional y componible**: encenderla/apagarla es un booleano. *Cuando una técnica se enciende con un booleano, compararla deja de ser una refactorización y pasa a ser un experimento.*
3. **El logging registra tamaños de entrada/salida.** Cuando dentro de meses una estimación salga mal, el log estructurado por etapa es la diferencia entre diagnosticar en minutos o en días.

```python
# app/generation/rag/retrieval/pipeline.py (fragmento)
async def retrieve(self, query: str) -> list[RetrievedChunk]:
    candidates = await self._vector_search.search(query, limit=settings.retrieval_candidate_pool_size)  # red amplia: 50
    if not settings.reranking_enabled:
        return candidates[: settings.retrieval_top_k]
    return self._reranker.rerank(query, candidates, top_k=settings.retrieval_top_k)  # salida estrecha: 5
```

> **Detalle async crítico:** la búsqueda vectorial es asíncrona (I/O a la BD); el reranking **no** (cómputo local). Una inferencia de cientos de ms en el event loop **bloquea todas las demás peticiones**. Si el reranker entra en un endpoint con concurrencia real, despáchalo a un thread pool (`asyncio.to_thread`). "El tipo de detalle que no sale en los tutoriales y sí en los incidentes."

## 1.8 La latencia y cuándo NO rerankear

El reranking se paga **en el peor sitio**: el camino crítico de cada consulta. Órdenes de magnitud (lote de 50): CPU ligero = decenas–cientos de ms; modelo potente sin GPU = segundos; con GPU = cientos de ms; API = inferencia + red, ~100–500 ms.

> La pregunta correcta nunca es "¿cuánto tarda el reranker?", sino **"¿qué fracción de mi presupuesto de latencia consume y qué me devuelve a cambio?"**. En la estimación, la generación del LLM tarda varios segundos → 200 ms de reranking es ruido. En un autocompletado de 300 ms de presupuesto → inasumible.

**Cuándo NO rerankear:**
- **El ranking vectorial ya es suficiente** (corpus pequeño y diferenciado, consultas muy específicas): reordenar lo ya ordenado = coste sin beneficio.
- **El cuello de botella está antes (problema de recall):** si los relevantes ni entran en el top-50, el problema es de chunking/embeddings/búsqueda. **El reranking no rescata lo que no se recuperó.**
- **El presupuesto de latencia no da.**

> **La señal de que el reranking ES la herramienta correcta:** los documentos relevantes **están** entre los candidatos, **pero no arriba**. Exactamente el caso del e-commerce enterrado bajo la app de pagos.

---

# PARTE 2 — ¿Compensa el reranking? Medición artesanal de relevancia

## 2.1 Por qué "parece que va mejor" no basta

Añades reranking, lanzas tres consultas, "tienen mejor pinta", cierras el ticket. Dos semanas después alguien pregunta por qué cada estimación tarda medio segundo más. Respondes "la recuperación mejoró". La pregunta inevitable: **¿cuánto?** Y "parece que va mejor" no sobrevive a una *code review*, a un comité de arquitectura ni al cliente que paga la factura.

El objetivo: convertir "parece que va mejor" en **"la precisión subió de 0,48 a 0,80 a cambio de 250 ms por consulta"**. No hace falta un framework ni un equipo de datos: una tarde, criterio de dominio y una hoja de cálculo. A esto se le llama **medición artesanal** — deliberadamente pequeña, manual y suficiente para la decisión que tienes delante.

## 2.2 Por qué la intuición engaña (tres sesgos)

- **Probamos con las consultas equivocadas:** elegimos las fáciles, las que nosotros formularíamos bien. Los usuarios reales escriben vago, mezclan temas, usan su jerga.
- **Recordamos lo memorable, no lo representativo:** un rescate espectacular domina la percepción aunque en el resto no cambie nada. La memoria pondera por impacto emocional; una métrica, por frecuencia.
- **Comparamos contra una referencia que se mueve:** evaluar a ojo el martes vs el jueves introduce ruido. Sin referencia fija, cada comparación usa una vara distinta.

La solución a los tres: **fijar de antemano un conjunto de consultas representativas con sus respuestas correctas, y medir TODAS las configuraciones contra él.** Ese conjunto es el **golden set**.

## 2.3 El golden set

Colección pequeña de **consultas reales del dominio**, cada una **anotada a mano** con los documentos que de verdad son relevantes. Es la verdad de referencia (*ground truth*). En el sistema de estimación, una entrada = una descripción de proyecto + la lista de presupuestos históricos que un estimador experto usaría de verdad como referencia (no los semánticamente parecidos, no los de la misma tecnología).

Tres decisiones, **ninguna técnica**:
1. **Qué consultas entran** — cubrir el uso real, no el cómodo: 2-3 frecuentes y directas, un par de difíciles conocidas (dominios colindantes como e-commerce/pagos), al menos una con términos exactos que respetar, y alguna larga y desordenada como las transcripciones reales.
2. **Cuántas** — **entre 5 y 20** bien elegidas. Lo que invalida la medición no es el tamaño, sino que la muestra no se parezca al uso real. *5 representativas informan más que 50 inventadas en 10 minutos.* Empieza pequeño: ampliar es trivial; tirar uno grande y malo, doloroso.
3. **Quién anota y con qué criterio** — quien usaría el resultado (el estimador). Escribe el criterio en una frase *antes* de anotar ("relevante si serviría como referencia directa de esfuerzo para este proyecto"), para evitar el desplazamiento silencioso entre la primera consulta y la tercera. **Anota en binario** (relevante/no): menos expresivo, pero consistente y suficiente.

## 2.4 Precision@k: la métrica que cabe en una servilleta

Lo que le importa al pipeline es la calidad de los **k primeros** que llegan al LLM (k = tamaño del contexto, p. ej. 5). La métrica natural:

> **precision@k = (documentos relevantes entre los k devueltos) / k**

Ejemplo: el golden set marca 4 presupuestos relevantes para la consulta de e-commerce; el sistema devuelve su top-5; 3 de los 5 son relevantes → **precision@5 = 3/5 = 0,60**. Se repite por cada consulta y se promedia: ese promedio describe la configuración. Una alternativa (con reranking) se mide contra **el mismo golden set** y se comparan los promedios en igualdad de condiciones.

Dos matices:
- **La k de la métrica = la k del sistema.** Si pasas 5 documentos, mide precision@5; medir precision@10 responde una pregunta que nadie hizo. (Si dudas entre pasar 3 o 5, mide ambas.)
- **Recall@k como complemento** (*"de lo que valía, ¿cuánto devolviste?"*). Si al anotar identificaste *todos* los relevantes (viable en corpus de empresa), calcularlo es gratis y detecta lo que la precisión no ve: el documento valioso que no aparece por ninguna parte. Métricas más sofisticadas que premian el orden dentro del top-k (familia **MRR**, **nDCG**) existen, pero **para decidir si una técnica entra en el pipeline, precisión y exhaustividad sobre tus k reales llegan de sobra.**

## 2.5 La otra columna: la latencia

La relevancia es media decisión; la otra media es lo que cuesta, y el coste dominante es la **latencia**. Dos precauciones al medirla artesanalmente:
- **Medir en caliente:** la primera consulta tras arrancar paga costes fijos (carga de modelos, conexiones, cachés frías) que no representan la operación normal. Se descarta.
- **Usar la MEDIANA, no la media:** 3-5 ejecuciones por consulta; la mediana resiste el pico atípico que con muestras pequeñas arrastraría la media.

El arnés vive en `scripts/`, **no** en las capas de la aplicación. Es deliberado: una herramienta de decisión puntual no necesita endpoint, ni tests, ni abstracción para futuros casos — convertirla en un "módulo de evaluación" es el clásico exceso de ingeniería que nadie quiere mantener. El **golden set es un archivo de datos versionado**: cambiarlo pasa por revisión, porque cambiar la vara de medir cambia el significado de todas las mediciones anteriores.

```python
# scripts/measure_retrieval.py (esencia)
TOP_K = 5
RUNS_PER_QUERY = 3

def precision_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int = TOP_K) -> float:
    top = retrieved_ids[:k]
    if not top:
        return 0.0
    hits = sum(1 for bid in top if bid in relevant_ids)
    return hits / len(top)
# measure(): por cada consulta, RUNS_PER_QUERY ejecuciones cronometradas (time.perf_counter),
# precision_at_k contra relevant_ids, y al final: media de precisión + mediana de latencia.
```

## 2.6 El marco de decisión: ganancia vs coste

Comparativa real del ejemplo:

| Configuración | precision@5 | Latencia mediana |
|---|---|---|
| Vectorial sola | **0,48** | **35 ms** |
| Vectorial + reranking | **0,80** | **290 ms** |

- **Lectura ingenua:** "el reranking multiplica la latencia por ocho" (cierta pero irrelevante).
- **Lectura correcta:** usa el **denominador adecuado = el presupuesto de latencia de la experiencia completa.** Tras la recuperación viene la generación del LLM (varios segundos), así que +255 ms es **<5%** del total y, a cambio, 2 de cada 5 documentos pasan de ruido a señal → **activar**.
- **El mismo número, decisión contraria:** en un autocompletado de 300 ms de presupuesto, esos +255 ms son el **85%** → descartar.

> **La técnica no es buena ni mala; es cara o barata *respecto a un presupuesto*, y el presupuesto lo fija el PRODUCTO, no el pipeline.**

**El cuadrante de decisión** (eje Y = ganancia de relevancia; eje X = latencia añadida como fracción del presupuesto): *Activar sin dudar* (gran ganancia, coste bajo) · *Evaluar contra presupuesto* (gran ganancia, coste alto) · *Ganancia marginal* (poca ganancia, coste bajo) · *Descartar* (poca ganancia, coste alto).

La zona traicionera: **ganancia pequeña con coste pequeño**. La tentación es activar "porque algo suma y apenas cuesta". Pero el coste nunca es solo la latencia: es el modelo extra que operar, la dependencia que actualizar, el modo de fallo nuevo que diagnosticar a las 3 de la mañana. *Una mejora de 0,02 rara vez paga ese peaje. Si la tabla no muestra una ganancia que se note, la respuesta senior es NO añadir la pieza.*

## 2.7 Lo que esta medición NO te da

- **Sin potencia estadística** con 10 consultas: una diferencia de 0,05 puede ser ruido de anotación. Decide con diferencias **grandes y consistentes** (0,48 → 0,80), no con décimas.
- **Arrastra el sesgo del anotador** (suficiente para decidir, no es la verdad universal).
- **Se detiene en la recuperación:** dice qué documentos llegan al LLM, no qué hace el LLM con ellos. Una recuperación perfecta no garantiza una estimación correcta, solo la hace posible. La evaluación sistemática de un RAG completo (frameworks dedicados, métricas sobre la generación) es otra disciplina, más adelante en el programa.

---

# PARTE 3 — Búsqueda híbrida: semántica + palabras clave

## 3.1 El problema: la semántica es miope para lo literal

Proyecto nuevo: "integración de pagos con **Stripe**, suscripciones y webhooks de facturación". El buscador devuelve proyectos con pasarelas de pago, cobros recurrentes... todos del campo semántico correcto. Pero el presupuesto que integró *exactamente* Stripe (que vale oro: tiene el esfuerzo real de pelearse con esa API) aparece en la **posición 14**.

¿Por qué? Para un modelo de embeddings, "Stripe" es aproximadamente sinónimo de "pasarela de pago". Esa generalización es su virtud (entiende que "cobros recurrentes" ≈ "suscripciones"), pero aquí es el problema: el **nombre propio**, el término exacto que distingue el documento perfecto, **se diluye en un vector que promedia todo el chunk**.

> **La búsqueda semántica es miope para lo literal.** El matching exacto de términos lo tenía resuelto la generación anterior de buscadores. **Búsqueda híbrida = no elegir:** ejecutar ambas búsquedas y fusionar.

## 3.2 Dos familias, dos puntos ciegos

| | **Léxica** (sparse / palabras clave) | **Semántica** (dense / vectorial) |
|---|---|---|
| Opera sobre | Términos literales (peso por rareza: IDF/BM25/TF-IDF) | Significado (embeddings, distancia coseno) |
| Ve bien | Identificadores exactos: "Stripe", "SAP", "ISO 27001" | Paráfrasis, sinónimos: "backoffice" ≈ "panel de administración" |
| Punto ciego | **No entiende paráfrasis** | **Diluye lo literal** (nombres propios, siglas, códigos) |

En un sistema de estimación conviven los dos tipos de consulta — descripciones conceptuales **y** menciones de tecnologías concretas — a menudo en la misma consulta. **La conclusión no es elegir mejor: es dejar de elegir.**

## 3.3 Full-text en PostgreSQL (la pieza que ya tienes)

El instinto dice "Elasticsearch". Resístelo: si los vectores ya viven en PostgreSQL, su motor full-text es maduro → cero infraestructura nueva, cero sincronización, las dos búsquedas a una consulta SQL de distancia. Piezas:

- **`tsvector`** — el documento preprocesado: tokenizado, en minúsculas, sin stopwords, con cada palabra reducida a su raíz (*stemming*: "integraciones"/"integración"/"integrar" colapsan). Depende del idioma → usar configuración **`'spanish'`**. Los términos que el diccionario no reconoce ("Stripe", "webhook") pasan casi intactos — justo lo que queremos.
- **`tsquery`** — la consulta con la misma normalización. **`websearch_to_tsquery`** acepta sintaxis natural de buscador y tolera entradas imperfectas.
- **Operador `@@`** — comprueba si un `tsvector` satisface una `tsquery`. **Índice GIN** (Generalized Inverted Index = índice invertido término→documentos) lo hace rápido. **`ts_rank`** puntúa por frecuencia/proximidad.

```sql
-- Columna generada: PostgreSQL mantiene el tsvector sincronizado, sin triggers
ALTER TABLE budget_chunks
  ADD COLUMN content_tsv tsvector GENERATED ALWAYS AS (to_tsvector('spanish', content)) STORED;
CREATE INDEX ix_budget_chunks_content_tsv ON budget_chunks USING gin (content_tsv);

-- La búsqueda léxica
SELECT chunk_id, ts_rank(content_tsv, query) AS lexical_rank
FROM budget_chunks, websearch_to_tsquery('spanish', :query_text) AS query
WHERE content_tsv @@ query
ORDER BY lexical_rank DESC LIMIT 50;
```

Dos honestidades: **`ts_rank` no es BM25** (no normaliza por longitud de documento con la misma sofisticación; hay extensiones de PostgreSQL con BM25, pero para miles/decenas de miles de chunks la diferencia es ruido frente a *tener* rama léxica). Y **Elasticsearch/OpenSearch siguen teniendo sitio** para corpus enormes o necesidades léxicas avanzadas — pero "no añadas un segundo almacén hasta que el primero se te quede pequeño".

## 3.4 Fusionar dos rankings que no hablan el mismo idioma

Las dos puntuaciones **no son comparables**: la coseno vive en un rango acotado, `ts_rank` en otra escala sin cota intuitiva. Sumarlas es "sumar metros con kilogramos". La tentación de **normalizar y pesar** (combinación ponderada, parámetro *alpha*) "funciona en la demo y se rompe en producción": la distribución de puntuaciones cambia con cada consulta (términos raros → léxica altísima; conceptual → bajísima), y la calibración de ayer queda descalibrada hoy. Trabajo permanente que nadie pidió.

**La solución elegante: ignorar las puntuaciones y usar solo las posiciones (ranks).**

## 3.5 Reciprocal Rank Fusion (RRF)

Cada documento recibe, de cada ranking donde aparece, una puntuación **inversamente proporcional a su posición**, y se suman:

```
rrf_score(d) = Σ  1 / (k + rank_i(d))
```

donde `rank_i(d)` = posición de `d` en el ranking `i` (empezando en 1), `k` = constante de suavizado (**típicamente 60**), Σ recorre todos los rankings.

Ejemplos con k=60: un doc **2.º en semántica y 5.º en léxica** → 1/62 + 1/65 ≈ **0,0315**. Un doc **1.º en semántica pero ausente en léxica** → 1/61 ≈ **0,0164**. **El documento que ambas búsquedas consideran bueno supera al campeón de una sola.**

> **RRF es una máquina de premiar el consenso:** aparecer razonablemente arriba en varios rankings vale más que arrasar en uno. Para el presupuesto de Stripe es el rescate exacto: la léxica lo sube por el término, la semántica lo mantiene digno por el tema, la fusión lo coloca arriba.

**La constante `k` es el único mando:** pequeña → dominan los primeros puestos (1/1 vs 1/2 es enorme); grande → fusión más "democrática". El **60** viene del paper original y es robusto en dominios muy distintos. **Tocarlo es optimización prematura.**

```python
# app/generation/rag/retrieval/fusion.py
from collections import defaultdict
RRF_SMOOTHING_K = 60

def reciprocal_rank_fusion(rankings: list[list[str]], k: int = RRF_SMOOTHING_K) -> list[str]:
    scores: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] += 1.0 / (k + rank)
    return [cid for cid, _ in sorted(scores.items(), key=lambda i: i[1], reverse=True)]
```

La función recibe **una lista de rankings, no exactamente dos** — RRF no sabe ni le importa cuántas fuentes fusiona. Esa generalidad la convierte en la pieza de fusión universal del pipeline (mañana fusionará multi-query o multi-índice sin cambiar una línea).

## 3.6 Orquestación y cuándo gana

Las dos ramas son consultas independientes a la misma BD → se lanzan en paralelo (`asyncio.gather`). **La latencia de la híbrida es la de la rama más lenta, no la suma.** El contrato es el mismo que cualquier búsqueda (consulta → lista de chunks), así que cambiar vectorial por híbrida es cambiar una pieza detrás de una configuración. Coste operativo: una consulta SQL extra (en paralelo), una columna generada (engorda la tabla, se recalcula al escribir) y un índice GIN (ocupa espacio); en un corpus de empresa, calderilla.

- **Gana con claridad:** consultas con identificadores exactos (tecnologías, productos, siglas, normas) — el pan de cada día en estimación; y consultas cortas y específicas.
- **Apenas mueve la aguja:** consultas puramente conceptuales y bien parafraseadas (la semántica ya lo hacía bien). RRF **degrada con elegancia**: si ambos rankings coinciden, el fusionado también.
- **Vigilar:** corpus/consultas en idiomas mezclados (español con terminología inglesa) — la config lingüística del `tsvector` procesa bien una parte y deja la otra sin stemming. No suele ser grave (los términos técnicos en inglés funcionan como identificadores exactos, donde la léxica brilla), pero explica resultados desconcertantes.

---

# PARTE 4 — Expansión y descomposición de consultas

## 4.1 El otro lado del mostrador: la consulta también es código

Hasta aquí todas las mejoras actuaban **después** de la consulta (índices, rankings, filtros). Pero hay un problema que ninguna mejora del lado de los documentos arregla: **la consulta misma**. Dos problemas distintos (y **no intercambiables**):

- **Consulta multi-tema:** la entrada real no es una consulta limpia, es una transcripción de 40 minutos donde el cliente salta de catálogo a app móvil a facturación a panel de administración. Su embedding es **el promedio de todos esos temas** → "un vector cerca de todo y de nada", que devuelve "proyectos grandes con muchas cosas" — la peor categoría para estimar (que se hace **por partidas**: el catálogo con referencias de catálogo, la integración con referencias de integración).
- **Lotería de la formulación:** mismo concepto, vocabulario distinto. El cliente dice "que los comerciales vean sus números desde el móvil"; el presupuesto relevante decía "dashboard de KPIs con versión responsive". Los embeddings cruzan paráfrasis mejor que nada anterior, pero no son inmunes: la formulación concreta decide los vecinos. *Que la recuperación dependa de la suerte al redactar es una fragilidad inaceptable en producción.*

## 4.2 Dos técnicas que parecen una

| | **Expansión (multi-query)** | **Descomposición** |
|---|---|---|
| Cuándo | 1 intención, muchas formas de decirla | varias intenciones mezcladas |
| Genera | N **paráfrasis** de la misma intención | N **sub-consultas**, una por tema (*workstream*) |
| Combate | la lotería de la formulación | el embedding promediado |
| Ejemplo | "que los comerciales vean sus números desde el móvil" → "dashboard de métricas comerciales móvil" / "KPIs de ventas en app móvil" / "informes de ventas desde smartphone" | la transcripción → "catálogo con gestión de inventario" / "app móvil para clientes" / "integración con facturación" / "panel con informes" |
| Fusión correcta | **premiar el consenso** (RRF) | **garantizar cobertura por tema** (round-robin / cuotas) |
| Si te equivocas | 4 boletos del sorteo equivocado | sub-temas artificiales que recuperan ruido |

> **Regla de decisión en una línea:** ¿la consulta pide UNA COSA que puede decirse de muchas maneras, o MUCHAS COSAS dichas a la vez? Lo primero → se expande. Lo segundo → se descompone. **Aplicar la técnica equivocada no es neutro.**

## 4.3 Generar las variantes: un LLM con la correa corta

La respuesta moderna es un LLM (antes: diccionarios de sinónimos y reglas). Pero "llamar al LLM sin más" es la versión ingenua. Dos disciplinas:

1. **Salida estructurada, no texto libre.** Las sub-consultas son entrada de la siguiente etapa, no prosa para un humano. Parsearlas con regex es fabricar un punto de rotura. Se define como esquema y se exige cumplirlo:

```python
class SubQuery(BaseModel):
    topic: str = Field(description="Short workstream label, e.g. 'billing'")
    query: str = Field(description="Standalone search query for this workstream")

class QueryDecomposition(BaseModel):
    sub_queries: list[SubQuery] = Field(min_length=1, max_length=4)
```

2. **Instrucciones que ACOTAN, no que inspiran.** El riesgo es que el LLM "mejore" demasiado: invente requisitos no mencionados, traduzca la jerga del dominio a sinónimos genéricos, fabrique ocho sub-consultas donde había dos temas. Cada creatividad contamina la recuperación. La instrucción se lee como una correa corta:

```text
DECOMPOSITION_INSTRUCTIONS:
- Produce at most 4 sub-queries. Fewer is better than fragmented.
- Each sub-query must be self-contained and understandable without the others.
- Preserve the exact domain terms (product names, technologies, acronyms). Never replace with generic synonyms.
- Never add requirements, features or technologies that the description does not mention.
- If the description covers a single topic, return exactly one sub-query that rephrases it cleanly.
```

Dos detalles que son decisiones: el **límite de 4 vive en dos sitios** — el esquema (`max_length=4`, que el modelo no puede violar → *garantiza*) y la instrucción (que explica el porqué → *orienta*); en producción quieres las dos. Y el **modelo se elige por configuración** (`settings.query_expansion_model`): no hace falta el más capaz, sino el más rápido que haga bien una tarea pequeña — esta llamada está en el camino crítico de cada búsqueda. *La expansión multi-query es el mismo patrón con otras instrucciones; no merece código aparte.*

## 4.4 Fusionar sin perder de vista para qué buscabas

Cada sub-consulta/variante produce su ranking. Sutileza que casi todo el material introductorio pasa por alto: **expansión y descomposición NO fusionan igual.**

- **Expansión → RRF (consenso).** Las N variantes buscaban lo mismo; un presupuesto bien posicionado en varias es señal fuerte. Hace flotar lo que todas respetan.
- **Descomposición → cobertura por tema (round-robin / cuotas).** Las N sub-consultas buscaban cosas deliberadamente distintas. Premiar el consenso aquí **sabotea el objetivo**: un presupuesto de catálogo jamás aparece en el ranking de facturación, y el tema con más presupuestos en el histórico inundaría el resultado, dejando los minoritarios sin representación. Hay que **garantizar que cada partida traiga sus referencias**.

```python
def interleave_rankings(rankings: list[list[RetrievedChunk]], top_k: int) -> list[RetrievedChunk]:
    """Round-robin entre rankings para garantizar cobertura por tema."""
    fused, seen_ids = [], set()
    for position in range(max(len(r) for r in rankings)):
        for ranking in rankings:
            if position < len(ranking) and ranking[position].id not in seen_ids:
                fused.append(ranking[position]); seen_ids.add(ranking[position].id)
                if len(fused) == top_k:
                    return fused
    return fused
```

La **deduplicación** (`seen_ids`) no es defensiva por capricho: un presupuesto que cubre dos temas aparece en dos rankings y, sin deduplicar, consumiría dos plazas del contexto contando una sola vez como información. Las N búsquedas son independientes → **en paralelo** (`asyncio.gather`): buscar cuatro veces cuesta aproximadamente lo que buscar una.

## 4.5 El precio y cuándo NO aplicar

Coste **estructuralmente distinto**: meten una generación de LLM en el camino crítico, **antes** de empezar a buscar.
- **Latencia:** ~200 ms–1 s (modelo pequeño, salida corta). El sumando más caro, y llega antes de que la búsqueda haga nada.
- **Tokens:** calderilla por consulta, pero multiplicada por cada consulta del sistema → al panel de costes desde el día uno.
- **Carga:** N búsquedas = N consultas a la BD y un conjunto de candidatos N veces mayor entrando a las etapas posteriores.

Mitigaciones, por rentabilidad: (1) el **modelo más pequeño** que haga la tarea con fiabilidad *—y verificarlo con ejemplos reales: "humilde" no es "gratis de verificar"—*; (2) **limitar a 3-4 variantes** (la quinta aporta ≈0); (3) **cachear reformulaciones** (la misma consulta no se repiensa; en sistemas con consultas parecidas, la tasa de acierto sorprende). Y la mitigación mayor: **no aplicar la técnica cuando no toca.** Una consulta corta, nítida y de un solo tema no necesita reformularse — sería pagar latencia para revolver un ranking que ya estaba bien.

Árbol de decisión: ¿varios temas? → SÍ: **descomposición**. → NO: ¿formulación nítida con vocabulario del dominio? → SÍ: **búsqueda directa** (coste cero) · NO: **expansión multi-query**. Heurística humilde (longitud/estructura de la consulta) como primera aproximación, y **la decisión queda en los logs** para auditar después qué camino siguió la consulta. *Caveat de medición:* estas técnicas brillan en las consultas difíciles, así que si el golden set solo tiene consultas de laboratorio, el veredicto saldrá injustamente tibio.

---

# PARTE 5 — Multi-índice y routing

## 5.1 El problema: el corpus que engorda y se vuelve heterogéneo

Los RAG reales engordan. El sistema ya almacena tres familias bien distintas: **presupuestos** (estructurados, telegráficos, partidas y cifras), **transcripciones** (lenguaje oral, redundante, divagante) y **documentación técnica** (densa, descriptiva). Ante "¿cuánto costó la integración con **SAP** en proyectos anteriores?", el documento que responde es un **presupuesto**, pero en un índice único el top-5 viene contaminado: dos chunks de transcripciones donde alguien *habló* de SAP, un fragmento de doc técnica sobre conectores, y solo después los presupuestos.

> El índice único responde a "¿qué se parece a esta consulta?" cuando la pregunta real era **"¿qué presupuesto se parece a esta consulta?"**. Esa diferencia, que un humano resuelve sin pensar, el índice no puede resolverla porque nadie se lo ha dicho.

Por qué se degrada un índice único mezclado: las familias tienen **texturas semánticas distintas** (un chunk de transcripción puede quedar más cerca por verbosidad, siendo menos útil); el **tipo dominante inunda** (10× más chunks de transcripciones que de presupuestos → el top-k tendrá la proporción del volumen, no de la utilidad); cada familia quiere **su propio preprocesamiento** (transcripción por turnos, presupuesto por partidas, doc por secciones); y **la operación sufre** (reindexar transcripciones no debería tocar presupuestos). Respuesta: **particionar** en colecciones, cada una con su preprocesamiento, esquema e índice.

## 5.2 Cómo particionar en PostgreSQL

| Criterio | **(A) Columna discriminadora** `document_type` | **(B) Tabla por familia** |
|---|---|---|
| Esquemas que divergen (importes vs interlocutores vs versiones) | ❌ columnas NULL por familia | ✅ esquema a medida |
| Asimetría de volumen | índices parciales (menos limpio) | ✅ un índice por población homogénea |
| Independencia operativa | ❌ todo cambio es global | ✅ operaciones locales |
| Búsqueda cruzada frecuente | ✅ una consulta, un `WHERE` | ❌ N consultas + combinación |
| Fricción inicial | ✅ una migración trivial | ❌ 3 tablas, 3 ingestas, 3 índices |

> **Regla:** si los esquemas de metadatos **divergen**, tablas separadas; si las familias son **variaciones de lo mismo**, columna discriminadora. **Los metadatos son la confesión involuntaria del diseño:** cuando te ves añadiendo `speaker_count` (NULL en todos los presupuestos) o `total_amount` (NULL en todas las transcripciones), la tabla única te dice que son entidades distintas conviviendo a disgusto.

En el sistema de estimación los esquemas divergen sin ambigüedad (`budget_chunks`, `transcript_chunks`, `technical_doc_chunks`) → **Opción B**. El precio se paga en mantenimiento (tres migraciones, tres índices, tres pipelines de ingesta), no en rendimiento.

## 5.3 El router: jerarquía de coste creciente

Con colecciones separadas, cada consulta necesita destino. La versión cara y vistosa se ha vuelto el reflejo por defecto, y casi nunca es la primera que toca. Recorrer **de menor a mayor coste**, usando lo caro solo para lo que lo anterior no resuelve:

- **Nivel 0 — el mejor router es no tener router.** Muchas consultas llegan con su destino implícito en el contexto de quien las hace: el flujo de estimación del backend **busca presupuestos siempre**. Capturarlo en el **contrato de la API** (parámetro explícito de colección o endpoints distintos): gratis, determinista, trazable. *Pregunta obligada antes de construir cualquier clasificador: ¿de verdad el servicio IA tiene que adivinar algo que el backend ya sabe?*
- **Nivel 1 — reglas deterministas.** Para cuando la consulta llega sin destino (buscador libre interno). Patrones de vocabulario inequívocos: "¿cuánto costó...?" → presupuestos; "¿qué dijo el cliente...?" → transcripciones. Frágiles ante la creatividad lingüística, pero gratis y transparentes; como primer filtro antes del clasificador caro, rinden.
- **Nivel 2 — el LLM como clasificador.** Para lo que las reglas no resuelven: modelo pequeño con salida estructurada.

```python
class SearchTarget(StrEnum):
    BUDGETS = "budgets"; TRANSCRIPTS = "transcripts"; TECHNICAL_DOCS = "technical_docs"

class RoutingDecision(BaseModel):
    targets: list[SearchTarget] = Field(min_length=1, max_length=3,
        description="Collections to search. Use several only when the query genuinely needs them")
    reason: str = Field(description="One short sentence explaining the choice")
# ROUTING_INSTRUCTIONS: clasifica en budgets/transcripts/technical_docs; elige una siempre que puedas,
# varias solo si de verdad hace falta; coste/esfuerzo/estimaciones → budgets, aunque mencione reuniones.
```

  Tres decisiones de diseño: (1) la salida es una **lista de destinos, no un destino con confianza** — cuando el clasificador duda entre dos colecciones, lo correcto es buscar en ambas, no elegir mal con un 0,55; modelar como lista convierte la duda en comportamiento bien definido en vez de un umbral arbitrario. (2) El campo **`reason` no es decorativo**: cuesta una frase y hace cada decisión auditable. (3) El **`StrEnum` cierra el universo**: el modelo no puede inventarse una colección que no existe.
- **Nivel 3 — buscar en todo.** Si ni el clasificador decide, **buscar en paralelo en todas y combinar**: el fallback honesto. Latencia = la colección más lenta. **Degradación elegante: en el peor caso, el multi-índice se comporta como el índice único — nunca peor.**

## 5.4 Combinar colecciones, y la procedencia como información

Las puntuaciones de colecciones distintas **no son comparables** (cada una con su textura y distribución) — versión agravada del problema de la híbrida. Fusionar por puntuación cruda hace que la colección de distancias generosas devore a las demás. Salidas sensatas: (1) si se necesita un ranking único, **fusión por posiciones o por cuotas** (los dos mejores de cada una), **nunca por puntuación cruda**; (2) muchas veces lo correcto es **no fusionar** y presentar agrupado por procedencia ("esto dicen los presupuestos; esto se habló en reuniones"), porque el consumidor final hace cosas distintas con cada familia y aplanarlas destruye información. Para todo ello, **cada chunk viaja con su etiqueta de procedencia** — lo que permite atribuir, auditar y depurar; perderla en la fusión es perderla para siempre.

*La semilla de algo más grande:* un componente que examina una petición y la delega en el especialista adecuado es un **patrón general de delegación** — el embrión de cómo los sistemas con agentes se reparten el trabajo (un coordinador que decide qué especialista atiende qué). La diferencia es de grado: nuestro router hace **una** clasificación acotada con esquema cerrado, sin razonamiento abierto ni herramientas. Esa contención es deliberada.

## 5.5 Cuándo NO particionar

Especialmente tentador de ignorar porque particionar *parece* arquitectura seria. **No particiones si:** el corpus es funcionalmente homogéneo (aunque los documentos tengan orígenes distintos); una colección concentraría el **95%** de las consultas (el router sería un peaje que casi siempre da la misma respuesta); o es "para cuando crezcamos" (deuda de mantenimiento contraída hoy contra una necesidad hipotética). **La señal legítima es observable y concreta:** resultados de una familia contaminando consultas dirigidas a otra, de forma recurrente y medible (el ejemplo de SAP no es hipotético). *Particionar sin la señal es sumar complejidad para un problema que no se tiene.*

---

# PARTE 6 — Filtrado contextual y temporal, y el orden del pipeline

## 6.1 El punto ciego de la similitud

Proyecto nuevo: portal de cliente con área privada, gestión documental y firma electrónica. La búsqueda encuentra un presupuesto casi calcado — mismo cliente, mismo alcance, misma estructura → similitud altísima, primera posición indiscutible. **Pero es de 2019:** frontend en AngularJS (obsoleto), firma con un proveedor que ya no existe, tarifas de otra época, prácticas que el estudio abandonó hace tres años. Como referencia de "qué partidas tiene", orienta; como referencia de "cuánto cuesta hoy", es **peligroso** — y el LLM no tiene forma de saberlo.

> **El embedding codifica lo que el texto *dice*, no *cuándo* se escribió, ni *con qué tecnología*, ni *para qué sector*, ni *si sigue siendo verdad*.** Esas dimensiones viven fuera del texto: en los **metadatos**. Bien usados son la técnica con mejor relación coste-beneficio del arsenal — la única cuyo coste de ejecución es *negativo*, porque **filtrar antes de buscar abarata todo lo que viene después**.

## 6.2 Filtros duros: reducir el universo antes de buscar

Condiciones sobre metadatos que **excluyen** documentos antes de que la similitud opine (proyecto React Native → presupuestos de tecnologías sin relación ni compiten; política de no estimar con referencias de >4 años → la fecha corta en seco).

```sql
SELECT chunk_id, embedding <=> :query_embedding AS distance
FROM budget_chunks
WHERE project_date >= :min_project_date
  AND technology = ANY(:relevant_technologies)
ORDER BY distance LIMIT 50;
```

> **LA TRAMPA (caveat crítico):** los índices aproximados como **HNSW no entienden de `WHERE`**. El índice navega su grafo buscando los vecinos más cercanos del **universo completo**, y el filtro se aplica **después**. Si pides 50 con un filtro que solo satisface el 5% del corpus, el índice devuelve sus 50 vecinos, el filtro descarta 48, y la consulta entrega **2 resultados — o cero — sin ningún error visible.**

Soluciones: **escaneo iterativo** (`hnsw.iterative_scan`, pgvector ≥ 0.8: sigue pidiendo candidatos hasta reunir los solicitados tras el filtro) o **índice parcial** (HNSW construido solo sobre las filas que cumplen la condición; para filtros muy frecuentes y selectivos). **La lección de fondo (el hábito):** cuando combines filtros con búsqueda aproximada, **verifica la cardinalidad de lo que vuelve y déjala en los logs** — "el filtro vació el resultado en silencio" es de los fallos más desconcertantes de depurar.

**Segunda condición:** los metadatos tienen que **existir y existir bien**. La fecha viene gratis; tecnología, sector o tamaño de equipo hay que extraerlos en la ingesta (con reglas, o con un LLM de extracción estructurada), **una vez por documento, nunca por consulta**. *La calidad de la extracción es el techo de todo:* un filtro duro sobre un metadato mal extraído **es peor que ningún filtro**, porque excluye con total confianza al mejor candidato y nadie ve el hueco. **Regla: filtros duros solo para metadatos en los que se confía; lo dudoso, como mucho, pondera.**

## 6.3 El tiempo: el metadato que nunca es opcional

Su efecto es universal y direccional: lo reciente vale sistemáticamente más (precios caducan, stacks rotan, prácticas cambian). Dos familias:

- **Ventana dura** (solo los últimos N años): simple de implementar y explicar, pero **brutal en el borde** — el de hace 3 años y 11 meses compite en igualdad, el de hace 4 años y 1 mes no existe. Importa si el corpus es escaso (y los históricos de empresa lo son): la ventana puede dejar fuera la única referencia decente de un tipo de proyecto raro.
- **Decaimiento continuo** (la edad como penalización progresiva, no veredicto). Forma habitual: exponencial. Único parámetro con lectura de negocio directa: la **semivida** (*half-life*) — cada cuántos días un presupuesto pierde la mitad de su peso.

```python
# app/generation/rag/retrieval/temporal.py
from datetime import date
def temporal_weight(document_date: date, half_life_days: int = 900) -> float:
    """Decaimiento exponencial: el documento pierde la mitad de su peso cada semivida."""
    age_days = (date.today() - document_date).days
    return 0.5 ** (max(age_days, 0) / half_life_days)   # max(...,0) evita pesos > 1 si la fecha es futura
```

Con semivida 900 días (≈ 2,5 años): **1 año → ≈76%**, **2,5 años → 50%**, **2019 → ≈15%**. El presupuesto de 2019 sigue existiendo (si es la única referencia de su especie, aparece, degradado), pero ya no le gana la primera posición a un equivalente reciente. **La semivida no se optimiza con una fórmula:** se elige con juicio de dominio ("¿a partir de cuándo dejarías de fiarte de las cifras?") y se revisa cuando el dominio cambie.

**Ventana vs decaimiento no es ideológico:** ventana cuando hay **razón categórica** (compliance, política de empresa, un cambio de era que invalide lo anterior); decaimiento para la **erosión gradual normal**. Se combinan: una ventana generosa como filtro de seguridad, y decaimiento dentro de ella como ordenación fina.

## 6.4 Ponderación dinámica (contextual) y su mayor peligro

El tercer nivel: que la **importancia de cada metadato dependa de la consulta**. Si la descripción gira sobre una tecnología concreta, la coincidencia tecnológica pesa mucho; si es para banca, la experiencia sectorial sube (arrastra regulación y plazos); si no menciona nada, esos metadatos callan. Se implementa como **multiplicadores sobre la ordenación final**, definidos **en configuración, no enterrados en el código**.

> **La advertencia más seria de la sesión:** es la técnica donde el exceso de ingeniería acecha con mejor disfraz. **Cada peso es un número mágico que alguien tendrá que justificar, recalibrar y depurar.** Un sistema con siete boosts contextuales interactuando es uno donde nadie sabe ya por qué un documento quedó tercero — has sustituido la opacidad del embedding por una **opacidad artesanal, que es peor porque encima parece controlable.**

Progresión sensata: **primero** filtros duros + decaimiento temporal (resuelven la mayor parte con dos decisiones explicables); **después** ponderación dinámica, solo para los metadatos donde haya *evidencia medida* de que aporta, con los multiplicadores documentados. **Ejercicio de humildad: si no puedes explicar en una frase por qué un boost vale 1,3 y no 1,5, no estaba listo para producción.**

## 6.5 Ensamblar el pipeline: el orden es el mensaje

Un pipeline moderno acumula etapas — reformulación, routing, filtros, búsqueda por dos ramas, fusión, reranking, ponderaciones. ¿En qué orden?

> **El principio en una línea: lo barato y excluyente, al principio; lo caro y fino, al final; lo blando, al cierre.**

```
Consulta
  │
  ▼  Reformulación (expansión/descomposición)   ─┐ operan sobre la consulta:
  ▼  Routing (a la colección adecuada)           ─┘ deciden QUÉ y DÓNDE se busca
  ▼  Filtros duros (metadatos: tecnología, fecha) ── lo excluyente, TEMPRANO (cada doc excluido es trabajo que nadie hará)
  ▼  Búsqueda híbrida (semántica + léxica, en paralelo)
  ▼  Fusión RRF (consenso de posiciones)          ── conjunto amplio de candidatos
  ▼  Reranking (cross-encoder)                    ── lo caro, TARDE, solo sobre los supervivientes
  ▼  Ponderación (temporal, contextual)           ── lo blando, AL CIERRE, sobre los finalistas
  ▼
 Top-5 al generador

Embudo de cardinalidad:  corpus (~miles) ─► filtrado ─► top-50 ─► 5 finalistas
```

**La asimetría deliberada:** los filtros duros van lo **más temprano posible** (ahorran trabajo a todo lo que sigue); las ponderaciones blandas, lo **más tarde posible** (ajustan sobre el conjunto pequeño donde equivocarse es barato y corregir es rápido). Los dos clásicos del pipeline mal montado: **rerankear documentos que un filtro iba a tirar** (dinero quemado) y **ponderar tan pronto que el ajuste blando expulsa candidatos antes de que el reranker los valore** (información destruida).

**Cada etapa es activable por configuración:** el pipeline completo es el **camino máximo, no el obligatorio**. No todas las consultas necesitan todas las etapas (la consulta simple y nítida no paga el peaje de la compleja), y poder encender/apagar cada pieza es la única forma de responder con datos a la pregunta que cada una debe contestar para quedarse: **¿qué aportas y cuánto cuestas?**

---

# Chuleta de una página (lo imprescindible)

| Técnica | Problema que resuelve | Cuándo usarla | Cuándo NO | Coste principal |
|---|---|---|---|---|
| **Reranking** (cross-encoder) | El orden del top-k es poco fiable | Relevantes *están* en candidatos pero no arriba | Recall pobre (no rescata lo no recuperado); ranking ya bueno; latencia justa | ~100–300 ms en el camino crítico |
| **Búsqueda híbrida** (semántica + léxica + RRF) | La semántica diluye términos literales | Identificadores exactos, consultas cortas/específicas | Consultas puramente conceptuales | 1 SQL extra + columna `tsvector` + índice GIN |
| **Expansión** (multi-query) | Lotería de la formulación (1 intención) | Formulación poco nítida, vocabulary mismatch | Consulta corta y nítida | 1 llamada LLM (~0,2–1 s) antes de buscar |
| **Descomposición** | Embedding promediado (varias intenciones) | Transcripciones, consultas multi-tema | Consulta de un solo tema | 1 llamada LLM + N búsquedas |
| **Multi-índice + routing** | Corpus heterogéneo contamina resultados | Contaminación recurrente y medible entre familias | Corpus homogéneo; 95% a una colección; "para crecer" | Mantenimiento (N tablas/índices/ingestas) |
| **Filtro duro** (metadatos) | Similitud ignora tecnología/sector/fecha | Metadatos en los que se confía | Metadato dudoso o mal extraído (peor que nada) | ≈ negativo (abarata el resto) — ojo a la trampa de HNSW |
| **Decaimiento temporal** | Lo viejo parece igual de relevante | Erosión gradual del valor (precios, stacks) | — (combínalo con ventana si hay razón categórica) | Un multiplicador; elegir semivida con juicio |
| **Ponderación dinámica** | Metadatos importan según la consulta | Solo con evidencia medida de que aporta | Por defecto (riesgo de "opacidad artesanal") | Números mágicos que justificar y depurar |

**Fórmulas a recordar:**
- `precision@k = (relevantes en top-k) / k`  ·  promediar sobre el golden set; medir latencia como **mediana** (en caliente).
- `rrf_score(d) = Σ 1 / (k + rank_i(d))`,  k ≈ 60  (solo posiciones, nunca puntuaciones).
- `temporal_weight = 0.5 ** (age_days / half_life_days)`,  semivida ≈ 900 días → 50%.

**Orden del pipeline:** reformulación → routing → **filtro duro** → híbrida → fusión RRF → **reranking** → **ponderación blanda** → top-5. *(Lo excluyente temprano; lo caro al final; lo blando al cierre.)*

**La meta-lección:** ninguna técnica se añade por moda. Cada incorporación se decide contra una tabla con dos columnas — **cuánto gana** (precision@k sobre el golden set) y **cuánto cuesta** (latencia mediana, como fracción del presupuesto que fija el producto). La diferencia entre un sistema que evoluciona con criterio y uno que acumula técnicas de moda no está en las técnicas, está en esa tabla.

---

## Cómo conecta con nuestro ejercicio

- **Ya tenemos pgvector** (Sesión 8) sobre un **único Postgres**. La rama léxica de la híbrida (`tsvector` + GIN) y los filtros duros (`WHERE`) caen sobre esa misma base **sin infraestructura nueva** — exactamente el argumento del artículo 3. La trampa de HNSW + `WHERE` (artículo 6) aplica tal cual a nuestra instalación.
- **Corpus pequeño** (orden de ~decenas de presupuestos): refuerza dos elecciones de la teoría — *candidate pool* hacia el extremo bajo (30–50) y **decaimiento temporal** preferible a la **ventana dura** (con pocos documentos, una ventana puede dejar un tipo de proyecto sin ninguna referencia).
- **Estructura por capas** (`app/generation/rag/retrieval/...` desde la Sesión 7): el reranker, la fusión, la reformulación, el router y el filtrado temporal encajan como **módulos componibles** de la capa de retrieval, cada uno activable por un flag de `settings` — justo el patrón "etapa = experimento de un booleano" que repiten los seis artículos.
- **Medición artesanal** (artículo 2): el `scripts/measure_retrieval.py` + un `golden_set.json` versionado es el siguiente entregable natural para decidir, con números de nuestro dominio, qué etapas de la Sesión 10 se quedan en el pipeline y cuáles se descartan.
