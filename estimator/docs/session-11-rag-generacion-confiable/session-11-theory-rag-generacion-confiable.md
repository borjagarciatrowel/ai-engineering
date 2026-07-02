# Sesión 11 — Generación confiable y evaluación (versión clara)

> Versión simplificada del resumen de los 6 artículos de la Sesión 11.
> Misma información, menos paja. Cada término técnico se explica en una frase.
> **Hilo conductor:** el mismo de siempre — un sistema que busca presupuestos antiguos parecidos para estimar un proyecto nuevo. La Sesión 9 lo hizo recuperar; la Sesión 10, recuperar bien. La Sesión 11 se ocupa de todo lo que pasa **después** de recuperar: preparar el material, combinarlo cuando se contradice, poder demostrar de dónde sale cada cifra, no dejar que el modelo mienta con seguridad, mantener el índice sano, y saber si todo eso funciona.

---

## Glosario base (léelo una vez y vuelve cuando haga falta)

| Término | Qué es, en una frase |
|---|---|
| **Content augmentation** | La capa entre recuperar y generar: convierte fragmentos crudos en evidencia destilada. |
| **Compresión extractiva / abstractiva** | Extractiva: copiar solo lo relevante, sin reescribir. Abstractiva: resumir con un modelo. |
| **Grounding / fundamentación** | Que una afirmación se derive de verdad de una fuente citada, y no de la imaginación del modelo. |
| **Síntesis** | Combinar varias fuentes que dicen cosas distintas sobre lo mismo en una sola estimación coherente. |
| **Mediana ponderada** | Estadístico central robusto a outliers, usado para anclar una cifra entre varias fuentes con distinto peso. |
| **Citación verificable** | Una referencia que resuelve a una fuente real, localiza la línea exacta, y es trazable hasta el origen. |
| **Integridad referencial** | Comprobación de que ninguna cita apunta a un id que no estuvo en el contexto (cita colgante). |
| **Alucinación con coartada** | Una cifra falsa citando una fuente real que no la respalda. La más peligrosa: pasa los filtros estructurales. |
| **Anclaje numérico** | Comprobación barata (sin LLM) de que una cifra cae dentro del rango de las fuentes que cita. |
| **Verificador / juez** | Un segundo modelo, más barato, instruido para dudar a favor de "no soportado". |
| **Deriva del índice** | Que los vectores dejen de representar fielmente los documentos, sin lanzar ningún error. |
| **Versionado de embeddings** | Grabar en cada vector el modelo, dimensión y preprocesamiento con que se generó, para no comparar espacios distintos. |
| **RAGAS** | Marco que calcula cuatro métricas de calidad RAG (fidelidad, relevancia, precisión y recall de contexto) sobre un golden set. |
| **Golden set** | Conjunto de casos de prueba con respuesta de referencia anotada a mano; el techo de calidad de cualquier métrica. |

---

## La idea en una página

Con recuperación (S9) y recuperación avanzada (S10) resueltas, el sistema trae buenos candidatos. Pero **traer bien no es generar bien**, y ahí aparecen otros seis fallos, cada uno con su herramienta:

| # | El fallo | La herramienta |
|---|----------|----------------|
| 1 | **Los fragmentos crudos son ruido.** Cabeceras, condiciones de pago, módulos que no vienen al caso — el 80% no sirve para esta consulta. | **Content augmentation** (Parte 1) |
| 2 | **Las fuentes se contradicen.** Tres presupuestos relevantes, tres cifras distintas, y ninguna técnica de preparación de contexto decide cuál pesa más. | **Síntesis multi-fuente** (Parte 2) |
| 3 | **Un id no es una citación.** `fin-2024-07#c3` no le dice a nadie de qué presupuesto sale ni qué línea lo respalda. | **Citación verificable** (Parte 3) |
| 4 | **La citación puede ser una coartada.** Impecable, resoluble, con enlace — y la fuente no dice lo que la estimación afirma. | **Detección y mitigación de alucinaciones** (Parte 4) |
| 5 | **El índice se pudre en silencio.** Un documento se corrige y el vector no se entera; se mezclan vectores de dos modelos distintos. Sin un solo error. | **Reindexación y versionado** (Parte 5) |
| 6 | **No sabes si el sistema mejora o empeora.** Cambias el prompt "porque parece mejor" y descubres la regresión semanas después, por una queja. | **Evaluación con RAGAS** (Parte 6) |

> **El hilo que atraviesa las seis partes:** cada etapa que puede tirar información, inventar una cifra, o dejar un vector obsoleto, tiene que **loguear qué hizo** y estar **medida contra un número**, no contra una impresión. "Parece mejor" no es un argumento en ninguna de las seis.

---

# Parte 1 — Content augmentation: preparar el contexto antes de generar

## El problema

La recuperación ya hizo su trabajo: filtró, reordenó con un cross-encoder, ponderó por recencia. El agujero está justo después, en el paso que casi nadie mira — **qué le pasamos exactamente al modelo que genera**. La respuesta habitual es "los fragmentos tal cual": se envuelven en delimitadores, se ordenan, se trunca lo que no cabe. Pero un fragmento de presupuesto real no es una ficha limpia: es cabeceras, condiciones de pago, un módulo que no viene al caso. Si estimas pagos y el 80% del fragmento es ruido de otra cosa, se lo estás pagando al modelo igual.

> **Content augmentation** es la capa entre recuperar y generar. No mejora la recuperación (ya está hecha) ni el prompt de generación. Mejora **el material** con el que el modelo trabaja.

## Por qué el ruido sale caro

Tres costes, los tres medibles: **tokens** (pagas por el ruido igual que por la señal), **atención** (el modelo no reparte atención de forma uniforme — lo que queda "perdido en el medio" de un fragmento largo se ignora aunque esté ahí), y **riesgo de alucinación** (más densidad de cifras irrelevantes, más fácil que el modelo agarre la equivocada y la arrastre a la línea que no es). Destilar el contexto no es solo eficiencia: es una primera línea de defensa contra alucinar.

## Pipeline componible: comprimir → extraer → ordenar → ajustar

```python
class AugmentedContext(BaseModel):
    evidence: list[BudgetEvidence]
    dropped_chunk_ids: list[str]
    token_estimate: int

def augment_context(
    chunks: list[RetrievedChunk],
    target_components: list[str],
    token_budget: int,
) -> AugmentedContext:
    """Stages: compress -> extract key points -> order -> fit budget.
    Every stage is independently toggleable and logged."""
    compressed = [compress_chunk(c, target_components) for c in chunks]
    evidence = [extract_key_points(c) for c in compressed]
    ordered = order_by_relevance(evidence)
    return fit_to_budget(ordered, token_budget)
```

La firma transporta una decisión: augmentation necesita saber **qué** estás estimando (`target_components`). La recuperación trabaja a nivel de consulta global; la destilación es específica de lo que vas a generar — así se descarta el módulo de autenticación de un fragmento cuando estimas pagos.

**Un detalle que atraviesa todas las etapas:** preservar el `chunk_id` de origen. Si el compresor produce texto huérfano sin id, la trazabilidad se destruye antes de crearla.

## Extractiva contra abstractiva: una decisión de riesgo, no de estilo

**Extractiva** — te quedas con las líneas que mencionan el componente objetivo, sin reescribir:

```python
def compress_chunk(chunk: RetrievedChunk, target_components: list[str]) -> CompressedChunk:
    """Extractive compression: keep only lines relevant to the target.
    No model call, no rewriting -> nothing can be hallucinated here."""
    targets = [t.lower() for t in target_components]
    kept = [
        line for line in chunk.text.splitlines()
        if any(t in line.lower() for t in targets) or _looks_like_figure(line)
    ]
    return CompressedChunk(
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        text="\n".join(kept) if kept else chunk.text,
        was_compressed=bool(kept),
    )
```

Barata, rápida, y **no puede inventar nada porque solo copia**. El `if kept else chunk.text` no es descuido: si el filtro se queda sin nada, devolver el fragmento entero es preferible a vaciar el contexto en silencio — el mismo error que un filtro de metadatos demasiado agresivo en recuperación. Por eso `was_compressed` viaja en la salida y se loguea.

**Abstractiva** — un modelo resume enfocándose en la consulta. Necesaria para fuentes narrativas (transcripciones) donde no hay "líneas" que filtrar, pero introduce **un segundo punto de generación**: si el resumen alucina, esa alucinación entra al contexto con apariencia de fuente. Se contiene forzando estructura, nunca prosa libre:

```python
class BudgetEvidence(BaseModel):
    chunk_id: str
    document_id: str
    component: str
    hours: float | None
    cost_eur: float | None
    sector: str | None
    project_year: int | None
    note: str  # short, grounded justification

def extract_key_points(chunk: CompressedChunk) -> BudgetEvidence:
    """Abstractive extraction constrained to a strict schema.
    The model fills fields, it does not write free prose. A missing
    figure stays None instead of being invented."""
    response = client.responses.parse(
        model=settings.augmentation_model,  # cheap tier
        input=[
            {"role": "system", "content": KEY_POINT_EXTRACTION_INSTRUCTIONS},
            {"role": "user", "content": chunk.text},
        ],
        text_format=BudgetEvidence,
    )
    evidence = response.output_parsed
    evidence.chunk_id, evidence.document_id = chunk.chunk_id, chunk.document_id
    return evidence
```

El esquema estricto hace dos cosas: restringe la salida a campos concretos, y permite el `None` explícito — la diferencia entre "el presupuesto no daba ese dato" y "el modelo rellenó el hueco". Ese `None` honesto vale más que una cifra de relleno.

## Ordenar: cargar los extremos

La atención no es plana — lo fuerte va al principio y al final, lo débil al medio:

```python
def order_by_relevance(evidence: list[BudgetEvidence]) -> list[BudgetEvidence]:
    """Edge-load the context: strongest evidence first and last."""
    ordered: list[BudgetEvidence] = []
    front = True
    for item in evidence:
        (ordered.insert(0, item) if front else ordered.append(item))
        front = not front
    return ordered
```

Y al final, el presupuesto de tokens manda: si no cabe todo, se descartan las piezas más débiles primero **y se registra cuáles**, para poder rastrear un fallo de generación hasta "dejé fuera la fuente que lo respaldaba".

## Trade-offs honestos

- **Comprimir para ahorrar puede salir más caro.** Un resumidor LLM por fragmento se multiplica por el número de fragmentos recuperados; ocho llamadas pueden costar más que pasar los fragmentos crudos. Mídelo, no lo asumas.
- **Tirar lo que no debías es un fallo silencioso.** Si el compresor extractivo busca "pagos" y el presupuesto dice "módulo de cobros", lo descarta — degradas el recall en augmentation, no en recuperación, y es más difícil de diagnosticar porque la recuperación parecía correcta.
- **La sobre-compresión borra el matiz.** "40h pero con la pasarela ya integrada" explica por qué esa cifra no es trasladable sin ajuste. Destilar hasta dejar solo "pagos: 40h" pierde justo lo que hacía útil la analogía.
- **Enriquecer también es generar.** Una cabecera sintética ("presupuesto sector fintech, 2024...") ayuda, pero la escribe un modelo: modelo barato, formato corto, nunca una afirmación que no esté en el fragmento.

## Lo que esto deja sin resolver

La augmentation limpia, estructura, ordena. Pero cuando dos presupuestos, ambos relevantes, ambos bien destilados, dicen cosas distintas sobre lo mismo, no decide nada. Eso ya no es preparar el contexto: es sintetizar fuentes.

---

# Parte 2 — Síntesis de múltiples presupuestos: combinar fuentes que se contradicen

## El problema no es combinar, es que discrepan

Tres presupuestos para "módulo de pagos": 40h, 90h, 55h. Los tres relevantes, los tres bien destilados. Un generador ingenuo hace una de tres cosas malas: promedia en silencio ("62 horas"), se queda con la primera que encuentra, o inventa un número intermedio plausible. Las tres producen una cifra **plausible**. Ninguna produce una cifra **defendible**.

Casi siempre hay una razón para la discrepancia, y suele estar en los datos: el de 40h tenía la pasarela ya integrada de un encargo anterior; el de 90h lo construyó desde cero hace dos años; el de 55h es reciente y de alcance comparable. **La discrepancia no es ruido, es información.** Aplastarla en "62 horas" tira lo más valioso que tenían los datos; una síntesis buena la conserva: "55–90h si se construye desde cero; ~40h si la pasarela ya está integrada" — una estimación que le dice al jefe de proyecto qué pregunta hacer antes de comprometerse.

## Pesar las fuentes con criterio

La recuperación ya calculó relevancia (reranker), recencia (decaimiento temporal) y similitud semántica. Esas tres señales bastan:

```python
class SourceWeight(BaseModel):
    relevance: float   # reranker score, normalized to 0..1
    recency: float     # temporal decay weight, 0..1
    similarity: float  # vector similarity, 0..1

def combined_weight(w: SourceWeight) -> float:
    """Single auditable weight per source.
    Three signals, not seven: the goal is a number you can defend in
    one sentence, not a pile of multipliers nobody can justify."""
    return 0.5 * w.relevance + 0.3 * w.recency + 0.2 * w.similarity
```

Regla dura y sana: si no puedes explicar en una frase por qué la relevancia pesa 0,5 y no 0,4, ese coeficiente no estaba listo. Empieza con pocas señales, añade más solo con evidencia de que ayudan.

## Agregar antes de generar: separar la aritmética del juicio

Pasarle todas las fuentes al modelo y pedirle que razone de una vez es simple, pero el número sale de una caja negra. La alternativa robusta: **calcular en código un ancla determinista** (mediana ponderada, dispersión, señal de contradicción) y dejar que el modelo razone **sobre esos agregados**, no que se invente la aritmética.

```python
def weighted_median(values_weights: list[tuple[float, float]]) -> float:
    """Robust central tendency: a single outlier budget cannot drag the anchor."""
    items = sorted(values_weights, key=lambda vw: vw[0])
    half = sum(weight for _, weight in items) / 2
    acc = 0.0
    for value, weight in items:
        acc += weight
        if acc >= half:
            return value
    return items[-1][0]

CONTRADICTION_REL_SPREAD = 0.5  # >50% spread between strong sources
STRONG_WEIGHT_FLOOR = 0.4

def aggregate_components(evidence, weights) -> list[ComponentAggregate]:
    # groups by component, computes weighted_median as anchor,
    # low/high from min/max hours, and:
    # contradiction = rel_spread > 0.5 AND at least two STRONG sources disagree
    ...
```

Dos decisiones deliberadas. **Mediana, no media**: robusta a outliers, un presupuesto de alcance muy distinto no debería arrastrar el ancla. **Contradicción por dispersión entre fuentes fuertes, no por dispersión a secas**: si la única cifra discordante viene de una fuente de peso bajo, es un outlier ignorable; si dos fuentes fuertes discrepan, es señal real. Esa distinción evita inundar al usuario de avisos falsos.

## Generar: rango, razón, fuentes

El esquema obliga a que cada componente sea un rango (colapsa a un punto cuando hay confianza), con su razonamiento y sus `source_chunk_ids`:

```python
class SynthesizedComponent(BaseModel):
    component: str
    low_hours: float
    high_hours: float          # equals low_hours when uncontested
    rationale: str              # why this number; explains any disagreement
    source_chunk_ids: list[str]
    contested: bool

SYNTHESIS_INSTRUCTIONS = """\
- Never blindly average conflicting figures. If sources disagree, find the
  reason (scope, recency, team, client complexity) and name it in `rationale`.
- Stay within the [low, high] range of the precomputed aggregate unless you
  can name an explicit reason to go outside it.
- When `contradiction` is true, return a real range; do not collapse
  disagreement into a false-precise single number.
- Every component lists the source_chunk_ids it is grounded on. Never cite
  a source that was not provided.
- If evidence is thin, say so in the rationale rather than projecting
  false confidence.
"""
```

El ancla determinista fija dónde está el centro y los bordes razonables; las instrucciones impiden salirse sin justificarlo. El modelo no inventa la aritmética, la explica con el juicio que la aritmética no tiene.

## Trade-offs honestos

- **Auditabilidad gana a simplicidad** para una cifra que alguien usará para comprometer dinero — pero las dos etapas cuestan más maquinaria y un riesgo nuevo: que el modelo se aparte del ancla sin justificarlo.
- **Pesar fuentes no arregla señales malas, las amplifica.** Si el reranker está mal calibrado o la semivida temporal no corresponde al dominio, el ancla ponderada será confiadamente incorrecta.
- **Mediana con N pequeño es tosca.** Con dos o tres fuentes, el valor real está más en el rango y su explicación que en el estadístico central.
- **El umbral de contradicción (50%) es política, no verdad.** Se ajusta observando cuántas alertas son accionables frente a cuántas son ruido.
- **El rango incomoda, y hay que defenderlo igual.** Colapsar un desacuerdo real en un "70h" limpio es mentir con apariencia de rigor.
- **Sintetizar no fabrica información.** Cuatro fuentes de relevancia baja siguen siendo malas fuentes, por mucho razonamiento que se les aplique encima.

## Lo que esto deja sin resolver

La síntesis entrelaza los hilos: la cifra de pagos ya no viene "de un presupuesto", viene de tres, ponderados. Y eso hace más urgente la pregunta que cualquiera va a hacer: **este 55, ¿de dónde sale exactamente?** Tener `chunk_id` en la salida es un principio, no todavía una respuesta verificable.

---

# Parte 3 — Citación y atribución verificable

## Un id no es una citación

`fin-2024-07#c3` al lado de "40h" no le dice a nadie de qué presupuesto sale, de qué año, ni qué línea lo respalda. **Una citación que un humano no puede resolver y un sistema no puede verificar es decoración**, no citación: da sensación de rigor sin la propiedad que importa — poder ir a la fuente y comprobarlo.

## Tres propiedades comprobables

1. **Resuelve**: el identificador apunta a una fuente real que el sistema puede recuperar.
2. **Localiza**: no solo un documento de cuarenta páginas — la línea o fragmento concreto.
3. **Es trazable hasta el origen**: existe un camino que cualquiera con permiso puede recorrer, idealmente con un clic.

```python
class Citation(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str               # human-meaningful
    project_year: int
    locator: str                       # exact source line backing the claim
    char_span: tuple[int, int] | None  # offsets into the source doc

def resolve_citation(chunk_id: str, retrieved: dict[str, RetrievedChunk]) -> Citation:
    """A KeyError here means the id was never in the retrieved context:
    dangling citation, handled by the integrity check, not silently."""
    chunk = retrieved[chunk_id]
    return Citation(
        chunk_id=chunk.chunk_id, document_id=chunk.document_id,
        document_title=chunk.document_title, project_year=chunk.project_year,
        locator=chunk.source_line, char_span=chunk.char_span,
    )
```

El `locator` es lo que decide si la citación es verificable de verdad o solo presentable — y depende de una decisión tomada mucho antes, en la **ingesta**: si no guardaste la línea o el rango de caracteres de origen al indexar, lo máximo que puedes citar es a nivel de documento. La citación de línea no se improvisa en generación.

## Integridad referencial: ninguna cita colgante

Incluso instruidos para citar solo fuentes provistas, los modelos a veces inventan un id con buena pinta que nunca estuvo en el contexto. Es el fallo de citación más peligroso porque **tiene el mismo aspecto que una cita legítima**. No se confía al modelo: se verifica en código, después de generar.

```python
class CitationIntegrityReport(BaseModel):
    resolved: list[str]
    dangling: list[str]  # cited ids that were never in the retrieved context

def check_citation_integrity(estimate: Estimate, retrieved_ids: set[str]) -> CitationIntegrityReport:
    resolved, dangling = [], []
    for component in estimate.components:
        for cid in component.source_chunk_ids:
            (resolved if cid in retrieved_ids else dangling).append(cid)
    if dangling:
        log.warning("dangling_citations", ids=dangling)
    return CitationIntegrityReport(resolved=resolved, dangling=dangling)
```

Política ante una cita colgante, de más a menos estricta: rechazar y reintentar, degradar el componente a "sin fuente verificable", o al menos no dejarlo salir del servicio. **La única opción inaceptable es ignorarla** — eso es entregar una atribución falsa con sello de verificada.

> **Importante:** esta comprobación es **estructural, no semántica**. Confirma que la fuente citada existe y estuvo en el contexto. No confirma que la fuente diga lo que la citación afirma. Necesaria, no suficiente.

## Formatos: estructura primero, presentación después

"¿Inline, notas al pie o enlaces?" no son alternativas excluyentes — son formas de renderizar la misma estructura. La citación estructurada es la fuente de verdad; el frontend decide cómo mostrarla. Inline es compacto pero se ensucia cuando una afirmación tiene varias fuentes (lo normal tras sintetizar); notas al pie escalan mejor; enlaces dan máxima verificabilidad pero abren una cuestión de permisos.

**Frontera de responsabilidad:** el servicio IA no debería emitir URLs ni asumir visibilidad. Emite `document_id` y `locator`, datos neutros. La capa de negocio sabe quién es el usuario y qué puede ver, y resuelve el enlace:

```ruby
class CitationLinkResolver
  def initialize(user); @user = user; end
  def link_for(document_id)
    document = HistoricalBudget.find(document_id)
    return nil unless @user.can_view?(document)
    Rails.application.routes.url_helpers.historical_budget_path(document)
  end
end
```

Si no hay permiso, el enlace simplemente no se ofrece y la citación se queda en su forma textual verificable. Verificabilidad y control de acceso no se contradicen: cada capa hace su parte.

## Trade-offs honestos

- **Citar a nivel de línea es una promesa que se paga en la ingesta.** Sin locator capturado, cita a nivel de documento y sé honesto sobre la granularidad — una citación de línea inventada es peor que una de documento sincera.
- **La citación estructurada es trabajo extra que el modelo a veces se salta**, y cumple peor cuanto más larga es la generación. La verificación de integridad es la red, no una garantía previa.
- **El enlace al original es la mejor verificación y la más frágil**: depende de rutas estables y permisos correctos. Un enlace roto o que expone un documento confidencial hace más daño que no tener enlace.
- **Demasiada citación cansa y deja de leerse.** A nivel de componente suele ser el grano correcto; el detalle línea a línea se reserva para auditoría.

## Lo que esto deja sin resolver

Con integridad referencial, ninguna afirmación cita una fuente que no existe. Pero la integridad referencial no confirma que el presupuesto citado diga "40h para pagos" — solo que existe y estuvo en el contexto. **Una citación que apunta a una fuente real que no la respalda es una alucinación con coartada.** Detectarla exige comprobar significado, no forma.

---

# Parte 4 — Detección y mitigación de alucinaciones

## Tres formas de alucinar, y las tres suenan razonables

- **Fabricación**: una cifra que no aparece en ninguna fuente. El caso puro, el más fácil de detectar si tienes las cifras a mano.
- **Atribución falsa**: la cifra existe, pero no en la fuente que se le adjudica (dos fuentes dicen 40h y 90h; el modelo presenta 40h citando el fragmento que en realidad decía 90). La trazabilidad miente aunque la cifra sea real. Como la citación resuelve, los filtros estructurales no la ven.
- **Extrapolación no fundamentada**: el modelo razona más allá de lo que las fuentes soportan (40h y 90h → "un módulo complejo con antifraude rondará las 160h"). No hay una fuente equivocada que señalar; hay un salto lógico que nadie pidió.

Ninguna suena absurda. Ese es el problema.

## Detectar: lo barato primero, lo caro después

La verificación cuesta (latencia, llamadas, dinero), así que se aplica en capas — lo que un `if` puede descartar no debería gastar una llamada a un modelo.

**Capa 1 — Anclaje numérico (determinista, sin LLM).** ¿La cifra cae dentro del rango de las fuentes que cita?

```python
def numeric_grounding(line: SynthesizedComponent, evidence_by_id: dict) -> bool:
    """Interpolation within the cited range is allowed; a figure outside the
    range of every cited source is an unsupported extrapolation."""
    cited_hours = [
        evidence_by_id[cid].hours for cid in line.source_chunk_ids
        if cid in evidence_by_id and evidence_by_id[cid].hours is not None
    ]
    if not cited_hours:
        return False  # no numeric support at all -> fabrication
    return min(cited_hours) <= line.low_hours and line.high_hours <= max(cited_hours)
```

Permitir interpolación dentro del rango es deliberado: si las fuentes dan 40 y 90, un 65 es una mezcla defendible. Lo que se marca es lo que queda **fuera** del rango: fabricación pura (sin soporte) y extrapolación (fuera de rango), ambas sin gastar un token.

**Capa 2 — Verificación semántica (el juez).** El anclaje no ve la atribución falsa (un 40h que por casualidad cae en rango pero cita el fragmento equivocado). Hace falta mirar significado:

```python
class ClaimVerdict(BaseModel):
    component: str
    supported: bool
    reason: str
    confidence: float

VERIFY_INSTRUCTIONS = """\
A claim is SUPPORTED only if the cited sources actually mention this
component and a figure consistent with the claim. A number present in no
cited source is NOT supported. Attributing a figure to a source that
discusses a different component is NOT supported. Do not be charitable:
when in doubt, return not supported."""
```

Es circular (el verificador también puede alucinar) y se reduce el riesgo por tres vías: **esquema estrecho** (`supported` es booleano, no redacción libre donde esconder ambigüedad), **modelo distinto y más barato** que el generador (para no compartir puntos ciegos), y **sesgo hacia "no soportado"** ante la duda. Un verificador permisivo es peor que no tener verificador — da falsa sensación de seguridad.

**Capa 3 — Consistencia (cara, selectiva).** Regenerar la misma cifra N veces: poca dispersión sugiere apoyo real, mucha sugiere adivinanza. Reservada para líneas de alto impacto o baja confianza, nunca para todo. **Trampa conceptual**: confunde "el modelo adivina" con "los datos genuinamente discrepan". Un componente que de verdad va de 40 a 90h según el alcance producirá muestras dispersas, y eso es incertidumbre honesta, no alucinación. La dispersión solo es sospechosa cuando las fuentes coinciden y el modelo no.

## Mitigar: prevenir, validar, abstenerse

**Prevenir** en las instrucciones del generador (prohibir extrapolar, exigir un campo `grounded` que obligue a posicionarse) reduce el volumen que llega a detección, pero da rendimientos decrecientes — cada prohibición nueva ayuda menos, y un prompt sobrecargado degrada la calidad general.

**Validar** combina las tres señales en una decisión graduada por línea, no binaria:

```python
def gate_line(line, evidence_by_id, verdict: ClaimVerdict) -> VerifiedLine:
    anchored = numeric_grounding(line, evidence_by_id)
    if anchored and verdict.supported:
        return VerifiedLine(..., status="grounded", confidence=verdict.confidence)
    if not anchored and not verdict.supported:
        log.warning("ungrounded_line_dropped", component=line.component)
        return VerifiedLine(..., low_hours=None, high_hours=None,
                             status="insufficient", confidence=0.0)
    # mixed signals: keep the figure but degrade confidence and flag for review
    return VerifiedLine(..., status="grounded", confidence=min(verdict.confidence, 0.4))
```

**Abstenerse** es la salida honesta cuando nada sostiene la cifra. `status="insufficient"` no es un fallo del sistema: es el sistema haciendo lo correcto. "No tengo datos suficientes para esto" es infinitamente más valioso que una cifra inventada que alguien usará para comprometer un plazo.

## Trade-offs honestos

- **La detección nunca es completa.** Asumir que cazarás todas las alucinaciones es, en sí mismo, una alucinación. El objetivo es reducir la tasa a un nivel aceptable para el riesgo del dominio, no llegar a cero.
- **El juez es un modelo, y los modelos alucinan.** Cuando el coste de un error es muy alto, la última verificación sigue siendo un humano.
- **La consistencia castiga la incertidumbre honesta si no se calibra.** Solo es señal de invención cuando contradice fuentes que coincidían.
- **Abstenerse de más vuelve el sistema inútil.** Un falso "grounded" (mentira confiada) suele costar más que un falso "insufficient" (utilidad perdida) — pero empujar el umbral hacia la abstención total es renunciar a hacer el trabajo.

## Lo que esto deja sin resolver

El sistema ahora verifica cada estimación que produce, línea a línea. Pero todas estas comprobaciones miran **una respuesta cada vez**. No dicen si el sistema, en conjunto, mejora o empeora cuando cambias el prompt, el modelo o el ensamblado de contexto. Eso es una disciplina distinta: medir.

---

# Parte 5 — Reindexación y versionado de embeddings

## El fallo que no da error

Todo el trabajo de citar, verificar y abstenerse descansa en una premisa que rara vez se cuestiona: que los vectores del índice representan fielmente los documentos, y que todos viven en el mismo espacio. Esa premisa se erosiona sola, y lo hace sin lanzar un solo error.

- **Deriva de contenido**: se corrige una cifra en el presupuesto original, pero el vector almacenado sigue representando el texto viejo. La búsqueda recupera un fragmento creyendo que dice 40h cuando el documento actual dice 60 — una atribución falsa que no es culpa del modelo, es culpa del índice.
- **Mezcla de versiones**: reembebes media colección con un modelo nuevo y dejas la otra mitad con el viejo. La similitud coseno entre un vector del modelo A y uno del B no significa nada — son espacios geométricos distintos —, pero la base de datos los compara igual y devuelve un número plausible. Sin error, sin excepción: solo recuperación silenciosamente rota.

## Versionar el índice: cada vector sabe cómo se hizo

"El mismo proceso" es más que "el mismo modelo": modelo, dimensión, si se normalizó, y la configuración de chunking/limpieza usada para producir el texto embebido.

```python
class EmbeddingVersion(BaseModel):
    model: str          # "text-embedding-3-small"
    dimensions: int      # 1536
    normalized: bool
    preprocessing_id: str  # id/hash of the chunking + cleaning config

    @property
    def key(self) -> str:
        return f"{self.model}:{self.dimensions}:{self.normalized}:{self.preprocessing_id}"
```

Esa `key` se guarda como columna `embedding_version` en cada chunk, y se vuelve **parte obligatoria** de toda consulta:

```sql
-- Retrieval always scopes to the single active embedding version.
FROM chunks
WHERE embedding_version = :current_version
ORDER BY embedding <=> :query_vector
LIMIT :k;
```

Ese `WHERE` no es una optimización: es una garantía de corrección. Sin él, una migración a medias contamina cada búsqueda en silencio.

## Cuándo y cómo reindexar

**Regla práctica:** si cambia un documento, reindexa ese documento (incremental, barato); si cambia el proceso (modelo, dimensión, chunking), reindexa todo (migración, cara).

**Incremental**, usando un hash del contenido de la fuente para saber qué está obsoleto sin reembeber lo que no cambió:

```python
def is_stale(chunk: StoredChunk, source_hash: str, current: EmbeddingVersion) -> bool:
    return chunk.source_hash != source_hash or chunk.embedding_version != current.key

async def reindex_incremental(documents: list[Document], current: EmbeddingVersion) -> None:
    for document in documents:
        source_hash = content_hash(document.text)
        existing = await get_chunks(document.id)
        if existing and not any(is_stale(c, source_hash, current) for c in existing):
            continue  # up to date, skip
        await delete_chunks(document.id)
        chunks = chunk_and_embed(document, current)  # reuses the existing ingestion pipeline
        await insert_chunks(chunks)
```

Válido **solo dentro de una versión**: insertar chunks nuevos junto a los viejos en cuanto cambia la versión activa es exactamente la mezcla que se quiere evitar.

**Migración de versión**, patrón blue/green aplicado a vectores: construir el índice nuevo al lado del viejo, verificar, cambiar de golpe.

```python
async def migrate_embedding_version(new: EmbeddingVersion) -> None:
    """Never mix versions in the live query space: build alongside, verify,
    then cut over atomically. If verification fails, nothing changes."""
    await build_shadow_index(new)
    if await verify_shadow_index(new):  # counts match, dimensions match, sample queries sane
        await promote_active_version(new)
        await drop_old_version_vectors()
    else:
        await discard_shadow_index(new)
        log.error("embedding_migration_aborted", version=new.key)
```

Mientras se construye el índice sombra, las consultas siguen sirviéndose de la versión activa; el usuario no nota nada. El cambio es un solo paso atómico — nunca hay un instante en que las dos versiones se mezclen en una consulta. **La verificación antes de promover no es opcional**: sin ella, un blue/green puede sustituir un índice bueno por uno roto en un solo paso.

## Trade-offs honestos

- **El incremental es una trampa fuera de su versión.** La pregunta antes de cada reindexación es siempre "¿cambió el documento o cambió el proceso?" — la respuesta decide la herramienta.
- **Migrar cuesta dinero y tiempo**: tantas llamadas al modelo de embeddings como chunks, más el almacenamiento duplicado del índice sombra durante la transición. Se planifica como migración, no como rutina.
- **La detección de obsolescencia es tan buena como tu captura de cambios.** El hash funciona si tienes el texto actual para hashearlo; si un presupuesto cambia en un sistema externo y nadie avisa, el índice no se entera.
- **"Nunca vamos a cambiar de modelo" es una de las frases más caras de un sistema RAG.** La columna `embedding_version` es un seguro barato desde el principio, aunque hoy solo exista una versión.
- **Reindexar por calendario malgasta o se queda corto.** Donde se pueda, ata la reindexación a eventos de cambio, no a un reloj.

## Lo que esto deja sin resolver

Con versionado y migraciones blue/green, el índice deja de pudrirse en silencio. Pero queda la pregunta que ninguna de estas garantías responde: has migrado a un modelo nuevo con todo el cuidado del mundo, la búsqueda no se ha roto — **¿pero ha mejorado?** El blue/green garantiza que no rompes nada visible; no garantiza que el cambio fuera una mejora. Eso se contesta midiendo.

---

# Parte 6 — Evaluación de calidad con RAGAS

## La pregunta que el sistema no sabe responder sobre sí mismo

Cada respuesta pasa por guardarraíles que comprueban si **esa respuesta concreta** es de fiar. Pero "¿es bueno el sistema, y está mejorando o empeorando?" es una pregunta distinta. Cambias el prompt porque "parece mejor", lo despliegas, y descubres la regresión semanas después por una queja. **Sin medida, cada cambio es una apuesta a ciegas con una venda muy bien puesta.**

RAGAS convierte la calidad en cuatro números calculables sobre un conjunto de pruebas y comparables entre versiones. No dice si una respuesta es verdad — eso es imposible de saber con certeza — pero dice si la versión de hoy es mejor que la de ayer, y dónde se pierde calidad si se pierde.

## Cuatro métricas, dos miden recuperación, dos miden generación

| Métrica | Qué mide | Capa | Necesita `ground_truth` |
|---|---|---|---|
| **Faithfulness** (fidelidad) | Qué proporción de las afirmaciones se puede inferir del contexto recuperado. Es la versión a escala de la detección de alucinaciones. | Generación | No |
| **Answer Relevancy** (relevancia) | Si la respuesta aborda de verdad la pregunta, sin irse por las ramas ni rellenar. | Generación | No |
| **Context Precision** (precisión de contexto) | Cuántos fragmentos recuperados son relevantes de verdad, y si están bien posicionados arriba. Evalúa reranker + búsqueda. | Recuperación | No |
| **Context Recall** (exhaustividad de contexto) | Si la recuperación trajo todo el contexto necesario para fundamentar la respuesta de referencia. | Recuperación | **Sí** |

**Leerlas juntas localiza el fallo, no solo lo señala:** fidelidad baja + contexto bueno (precisión y recall altos) → problema de generación, el modelo no usó bien lo que tenía. Fidelidad alta + recall bajo → el modelo se porta bien con lo poco que le llega, pero la recuperación no le da lo que necesita.

## El golden set es el techo de tus métricas

RAGAS calcula números sobre el conjunto que le des; esos números solo valen lo que valga el conjunto. Un golden set pequeño, sesgado o con referencias mal hechas produce **métricas confiadas y sin sentido** — y nada en la salida avisa de ello.

Un buen golden set para estimación cubre el espectro real, no solo lo fácil: casos con presupuestos comparables y respuesta clara, casos ambiguos, casos donde las fuentes se contradicen (para comprobar que el sistema entrega un rango honesto), y **crucial: casos donde la respuesta correcta es "no hay datos suficientes"**. Si el golden set no incluye un caso que debe terminar en abstención, no se está midiendo si el sistema sabe abstenerse — se está premiando que conteste siempre. Los casos adversariales no son opcionales.

## Implementación

```python
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy, context_precision, context_recall

def build_eval_dataset(golden: list[GoldenItem], pipeline) -> Dataset:
    rows = {"question": [], "answer": [], "contexts": [], "ground_truth": []}
    for item in golden:
        result = pipeline.run(item.transcript)  # real retrieval + generation
        rows["question"].append(item.question)
        rows["answer"].append(result.answer_text)
        rows["contexts"].append([chunk.content for chunk in result.retrieved_chunks])
        rows["ground_truth"].append(item.ground_truth)
    return Dataset.from_dict(rows)

def run_ragas(golden: list[GoldenItem], pipeline) -> dict[str, float]:
    dataset = build_eval_dataset(golden, pipeline)
    scores = evaluate(dataset, metrics=[faithfulness, answer_relevancy, context_precision, context_recall])
    log.info("ragas_scores", **scores)
    return scores
```

Dos notas honestas: RAGAS usa por dentro un LLM juez y un modelo de embeddings (funciona en español sin problema); y **la API de RAGAS cambia de forma notable entre versiones** — fija la versión en el proyecto y comprueba los nombres exactos contra ella.

## Dos modos, no los confundas

**Offline como puerta de regresión** (necesita `ground_truth`, solo posible sobre el golden set): antes de desplegar un cambio, pasas el golden set por la versión candidata y comparas sus cuatro métricas con las de la versión actual. Si fidelidad o recall caen, no despliegas.

**Monitorización en producción** (sin referencia — nadie ha escrito de antemano la estimación correcta para una consulta real): solo fidelidad y relevancia son calculables sobre tráfico vivo, nunca context recall.

```python
async def monitor_production_sample(estimates: list[ServedEstimate]) -> dict:
    """Reference-free quality monitor on sampled live traffic.
    Alert on downward drift, not on absolute values."""
    dataset = Dataset.from_dict({
        "question": [e.question for e in estimates],
        "answer": [e.answer_text for e in estimates],
        "contexts": [[c.content for c in e.retrieved_chunks] for e in estimates],
    })
    return evaluate(dataset, metrics=[faithfulness, answer_relevancy])
```

Súmale las señales operativas que ya producen los guardarraíles (tasa de abstenciones, citas colgantes cazadas, líneas degradadas) y tienes un cuadro de mando que se mueve en el tiempo.

## Trade-offs honestos

- **El juez de RAGAS es un modelo, con la misma circularidad de siempre.** Una fidelidad de 0,82 no es "82% verdadero": es un número comparable. Úsalo como tendencia entre versiones, no como verdad absoluta.
- **Un techo bajo no se ve.** Un golden set pequeño da números igual de confiados que uno bueno — invertir en el golden set no es preparación para evaluar, **es** la evaluación.
- **Optimizar una métrica sola estropea las otras** (ley de Goodhart en versión RAG): perseguir fidelidad a toda costa hace que el sistema se abstenga más y conteste menos, hundiendo la relevancia. Las cuatro se leen juntas.
- **La deriva en producción no siempre es regresión.** Puede venir de que esta semana entran consultas más difíciles, no de un bug — cruza la deriva con qué cambió de verdad antes de actuar.
- **Evaluar es un lote, no una petición.** Muchas llamadas al juez por caso, presupuestado y programado offline; confundirlo con un guardarraíl en línea es caro y no resuelve ninguno de los dos problemas.

---

# Chuleta de una página

| Técnica | Qué resuelve | Cuándo SÍ | Cuándo NO | Coste |
|---|---|---|---|---|
| **Content augmentation** | Fragmentos crudos son ruido para la consulta concreta | Siempre que el fragmento traiga contenido fuera de alcance | Fuente ya es una ficha limpia sin ruido | Extractiva: ~gratis. Abstractiva: 1 llamada LLM por fragmento |
| **Síntesis multi-fuente** | Fuentes relevantes se contradicen entre sí | 2+ fuentes fuertes con cifras distintas | Fuentes coinciden (cualquier media sirve) | Aritmética determinista + 1 llamada de razonamiento |
| **Citación verificable** | Un id no es una atribución comprobable | Siempre que la salida se use para decidir algo | — (siempre aplica en algún grado) | Depende del locator capturado en ingesta |
| **Anclaje numérico** | Fabricación y extrapolación de cifras | Toda línea generada, primera pasada | — (barato, aplícalo siempre) | Determinista, sin llamada |
| **Juez semántico** | Atribución falsa (cita real, contenido no coincide) | Lo que el anclaje no decide | Ya rechazado por anclaje | 1 llamada a modelo barato por línea |
| **Consistencia (N-samples)** | Detectar adivinanza vs. incertidumbre honesta | Líneas de alto impacto o baja confianza | Todo (inviable) o fuentes ya dispersas | N llamadas de generación |
| **Versionado de embeddings** | Mezcla de espacios vectoriales incomparables | Desde el día uno, aunque solo haya una versión | — | 1 columna + 1 filtro `WHERE` |
| **Reindexación incremental** | Deriva de contenido en documentos individuales | Documento nuevo o corregido | Cambió el modelo/proceso | Coste del pipeline de ingesta, por documento |
| **Migración blue/green** | Cambio de modelo de embeddings o proceso | Cambia el modelo, dimensión o chunking global | Documento aislado (usa incremental) | Reembeber todo el corpus + espacio duplicado temporal |
| **RAGAS offline** | Saber si un cambio mejora o empeora el sistema | Antes de desplegar cualquier cambio | Como guardarraíl en línea (es un lote) | Golden set + N llamadas al juez × tamaño del set |
| **RAGAS en producción** | Detectar deriva de calidad sin referencia | Monitorización continua, solo fidelidad/relevancia | Context recall (no hay ground truth en vivo) | Muestreo de tráfico + llamadas al juez |

**La meta-lección, otra vez:** cada etapa que puede tirar información, inventar una cifra o dejar un vector obsoleto **loguea qué hizo**, y cada técnica se juzga contra una tabla de dos columnas — cuánto gana, cuánto cuesta — nunca contra "parece mejor".

---

## Cómo conecta con nuestro ejercicio

- **Ya tenemos generación con citación básica.** `app/generation/rag/estimator.py` implementa el pipeline completo (reformular → embed → recuperar → truncar a presupuesto → **augment** vía `context_assembler.build_context_block` → generar → `validate_citations`). Es la Parte 1 (augmentation) ya construida, y la mitad de la Parte 3 (citación) — pero `RetrievedChunk` (`id`, `budget_id`, `source_id`, `collection`, `estimated_hours`) y `validate_citations` (`validation.py`) verifican **membresía de id**, no `locator` a nivel de línea ni trazabilidad hasta el documento original. Falta la capa `Citation` con `document_title`/`locator`/enlace resuelto por permisos.
- **La generación actual es de una sola pasada, no dos etapas.** `estimator.py` pide al modelo que razone y cite de una vez sobre los chunks rankeados; no hay agregación determinista por componente (mediana ponderada, `contradiction`, `low`/`high`) antes de generar. La Parte 2 completa (síntesis multi-fuente con ancla auditable) es la brecha más clara para este ejercicio: hoy no hay lógica explícita de "combinar fuentes que se contradicen", solo lo que el prompt le pida al modelo hacer implícitamente.
- **No hay detección de alucinaciones más allá de `validate_citations` + `check_coherence`.** El grep confirma cero lógica de entailment/faithfulness/NLI. El anclaje numérico (Parte 4, capa 1) es la pieza más barata de portar primero — determinista, sin LLM, cazaría fabricación y extrapolación con lo que ya existe en `RetrievedChunk.estimated_hours`.
- **Cero versionado de embeddings.** `EMBEDDING_MODEL = "text-embedding-3-small"` es una constante (`config.py`), no una columna. Las tres tablas de chunks (`budget_chunks`, `transcript_chunks`, `technical_doc_chunks` de la migración `0004_session10_multi_index.py`) no tienen `embedding_version`. Es divergencia real y barata de cerrar (Parte 5): una columna + un `WHERE` antes de la próxima migración de modelo, no una reescritura.
- **El harness de evaluación mide precisión@k y latencia (S10-live), no RAGAS.** `evals/metrics.py` + DeepEval `GEval` dan una base de juez-LLM ya existente; falta cablear `faithfulness`/`answer_relevancy`/`context_precision`/`context_recall` sobre el mismo `golden_dataset.json` — el golden set ya tiene la forma correcta (15 presupuestos, 5 transcripciones, 4 docs técnicos, 60 tareas), pero conviene revisar que incluya casos de contradicción y de abstención antes de fiarse de los números.
- **Corpus pequeño** (15/5/4, 60 tareas): refuerza, como en S10, decaimiento temporal sobre ventana dura y N-samples de consistencia reservados a lo crítico — con pocas fuentes por componente, la mediana ponderada es una herramienta tosca y el rango importa más que el punto central.
