# Sesión 6 — Teoría: calidad del dato, ingesta y pipeline de datos para RAG

> Módulo 3 del programa. Cinco artículos que cubren todo lo que ocurre **antes** de
> vectorizar un solo documento: por qué se elige RAG, cómo auditar las fuentes, cómo
> extraer el contenido, cómo limpiarlo y validarlo, y cómo proteger los datos sensibles.
> La vectorización propiamente dicha (embeddings, chunking, espacio vectorial) empieza
> en la Sesión 7; las bases de datos vectoriales, en la Sesión 8. Todo eso se monta
> encima del cimiento que construye esta sesión.

---

## 0. La idea en una página (para cualquiera)

Imagina que quieres montar una biblioteca que responda preguntas. Da igual lo lista que
sea la persona del mostrador (el modelo de IA): si los libros del almacén están
duplicados, desactualizados, mal etiquetados o llenos de páginas en blanco, las
respuestas serán malas. Y lo peor es que **sonarán igual de seguras que las buenas**,
porque el sistema no inventa información: la recupera y la presenta. Si recupera basura,
presenta basura bien formateada.

El Módulo 3 trata exactamente de esto. Hay una frase que conviene interiorizar:

> *"No amount of clever chunking or fancy architecture can fix fundamentally bad data."*
> (Ninguna estrategia de troceado ni arquitectura sofisticada arregla datos que son
> malos de raíz.)

Por eso, antes de tocar embeddings, dedicamos tres sesiones enteras a los datos. El
recorrido de la Sesión 6 es una cadena de cinco eslabones:

1. **¿Por qué RAG y no otra cosa?** — Marco de decisión para defender la arquitectura
   ante cualquier stakeholder (Artículo 1).
2. **¿Qué tengo y en qué estado está?** — Auditoría e inventario de las fuentes antes de
   procesar nada (Artículo 2).
3. **¿Cómo convierto cada formato en texto procesable?** — Pipeline de extracción
   multi-formato con un contrato común (Artículo 3).
4. **¿Cómo garantizo que el contenido es correcto?** — Limpieza, normalización y
   validación de los datos (Artículo 4).
5. **¿Cómo protejo los datos personales?** — Anonimización y cumplimiento de GDPR
   (Artículo 5).

Al final del módulo no tendremos código brillante, sino algo más valioso: **un corpus
que un equipo de producción podría defender ante un interlocutor legal, comercial,
técnico o regulatorio**. Ese es el estado mínimo desde el que tiene sentido convertir el
corpus en vectores.

A lo largo de toda la sesión se usa como hilo conductor el **Proyecto 2**: un sistema que
recibe transcripciones de reuniones de cliente y genera estimaciones de proyectos
software basándose en histórico de presupuestos pasados.

---

# PARTE 1 — Calidad del dato y la decisión arquitectónica (CAG vs RAG)

## 1.1 El verdadero techo del CAG: no es solo el context window (para cualquiera)

CAG (*Context-Augmented Generation*) significa, en cristiano, "meterle al modelo todo el
contexto de golpe en cada llamada". Funciona de maravilla con poco material. Cuando el
corpus crece, se rompe. Un ingeniero junior suele creer que solo se rompe por una razón:
"no cabe en el contexto". Es una simplificación útil pero engañosa.

El CAG tiene un techo compuesto por **cuatro restricciones que operan a la vez**:

1. **Context window.** El modelo declara una capacidad máxima de tokens por llamada.
   Cuando el corpus la supera, no se puede inyectar entero. Restricción **binaria y
   obvia**.
2. **Coste por consulta.** El coste se dispara linealmente con los tokens de entrada. Un
   sistema que cuesta 3 céntimos por consulta es desplegable; uno que cuesta 2 € no lo es
   para casi ningún caso de uso. Restricción **continua**, y suele ser la que mata el
   proyecto antes que la primera.
3. **Latencia.** Procesar 100K tokens lleva varios segundos incluso en modelos
   optimizados. Para un asistente conversacional síncrono es inviable; para un batch
   nocturno, irrelevante. Depende **del producto**, no de la arquitectura.
4. **Degradación de atención sobre contextos largos.** La más subestimada. Los modelos
   **no procesan 200K tokens con la misma fidelidad que 5K**. El fenómeno se documenta
   como *lost in the middle*: la información en la mitad del contexto se recupera peor que
   la de los extremos. Aunque el corpus *quepa*, no se procesa con la misma calidad que si
   solo se inyectaran los fragmentos relevantes.

Conviene fijar las cuatro como un objeto formal:

```python
from dataclasses import dataclass

@dataclass
class CAGViability:
    fits_in_context_window: bool   # ¿Cabe técnicamente?
    cost_per_query_acceptable: bool  # ¿Es viable económicamente?
    latency_acceptable: bool         # ¿Responde dentro del SLA?
    quality_holds_with_load: bool    # ¿La calidad se mantiene con carga?

    def is_viable(self) -> bool:
        return all([
            self.fits_in_context_window,
            self.cost_per_query_acceptable,
            self.latency_acceptable,
            self.quality_holds_with_load,
        ])
```

**Conclusión empírica: basta con que una falle para que la arquitectura no sea viable. Y
casi nunca falla solo una.**

## 1.2 Por qué la calidad del dato es la variable de control

Un sistema RAG no genera información: la **recupera** y la **presenta**.

- Si lo que se recupera es ruido → se presenta ruido bien formateado.
- Si está desactualizado → se presenta desinformación con apariencia de respuesta
  autorizada.
- Si está duplicado, inconsistente o mal estructurado → ningún reranker ni cross-encoder
  lo arregla en el momento de la consulta.

Esta es la diferencia operativa entre un equipo que **pone** un RAG en producción y uno
que lo **intenta**. El primero invierte semanas en auditoría, normalización y validación
del corpus antes de vectorizar nada. El segundo vectoriza de inmediato para ver
resultados rápido, y pasa los seis meses siguientes intentando entender por qué el
sistema responde mal de forma intermitente.

Lo traicionero es que **el sistema parece funcionar bien al principio**: con un corpus
pequeño y queries de prueba elegidas por el equipo, las respuestas son aceptables. La
degradación aparece cuando el corpus crece, cuando llegan preguntas no anticipadas, y
cuando los datos se vuelven incongruentes consigo mismos (dos versiones contradictorias
del mismo presupuesto en el índice). En ese momento ya es muy tarde: el pipeline está
construido sobre supuestos que no se cumplen.

## 1.3 El pipeline RAG como abstracción de seis pasos

La descomposición canónica (popularizada por equipos como Databricks) tiene seis pasos:

1. **Ingest** — recoger los datos de las fuentes (BBDD, ficheros, APIs, sistemas de
   archivos).
2. **Parse** — extraer texto y metadatos limpios de cada formato (PDF, DOCX, JSON…).
3. **Chunk** — trocear los documentos en fragmentos de tamaño adecuado.
4. **Embed** — convertir cada fragmento en un vector.
5. **Retrieve** — dada una consulta, recuperar los fragmentos más relevantes.
6. **Generate** — pasar al LLM la consulta junto con los fragmentos recuperados.

## 1.4 Offline vs online: la línea que cambia toda la arquitectura

La trampa de esa lista es que parece un flujo lineal en tiempo real. No lo es. Los seis
pasos se reparten en **dos pipelines distintos**:

| | **Pipeline offline (indexación)** | **Pipeline online (consulta)** |
|---|---|---|
| Pasos | 1–4: ingest → parse → chunk → embed | 5–6: retrieve → augment → generate |
| Ejecución | Background, sin usuario esperando | Síncrono, usuario esperando |
| Presupuesto de tiempo | Minutos a horas | < 3 segundos (típico) |
| Disparado por | Eventos (subida de doc, cron nocturno) | Preguntas del usuario |
| Acceso a | Datos crudos | Solo vectores y metadatos indexados |

Materializar esta separación cambia la estructura del servicio IA: no es lo mismo un
endpoint que lo hace todo que **dos endpoints con responsabilidades disjuntas** (por
ejemplo `POST /index/run` asíncrono y `POST /query` síncrono).

Consecuencias prácticas: el pipeline offline **puede usar modelos pesados** (OCR,
embeddings grandes, validadores estrictos) porque la latencia no importa; el online tiene
que ser **quirúrgico**: solo búsqueda vectorial rápida, construcción del prompt y llamada
al LLM. Mezclar responsabilidades es uno de los antipatrones más comunes en RAG mal
arquitecturado. Para el backend de negocio (Rails u otro stack) esto significa invocar al
servicio IA por **dos vías**: la indexación es asíncrona (dispara y olvida); la query es
síncrona y bloqueante. Si la distinción no está clara desde el primer día, terminas con
un servicio que se cuelga porque intenta indexar 200 PDFs mientras procesa una consulta.

## 1.5 El árbol de decisión: CAG, RAG, fine-tuning e híbrido

La decisión se articula sobre **cuatro ejes**:

1. **Volumen del corpus** relativo al context window (cargar el 95% es posible pero
   degrada calidad).
2. **Frecuencia de actualización** de los datos.
3. **Requisito de trazabilidad** (¿hay que citar la fuente concreta de cada afirmación?).
4. **Sensibilidad de los datos** (PII, control de acceso por usuario).

Materializado como código (su valor pedagógico es obligarte a explicitar los criterios):

```python
class Architecture(Enum):
    PURE_CAG = "pure_cag"
    HYBRID_CAG_RAG = "hybrid_cag_rag"
    PURE_RAG = "pure_rag"

def recommend_architecture(corpus: CorpusProfile, model: ModelProfile) -> Architecture:
    context_usage = corpus.total_tokens / model.context_window

    # Trazabilidad obligatoria → RAG (CAG no atribuye a fragmentos concretos).
    if corpus.requires_source_attribution:
        return Architecture.PURE_RAG
    # Control de acceso por usuario → RAG (en CAG todo el corpus va en cada llamada).
    if corpus.requires_per_user_access_control:
        return Architecture.PURE_RAG
    # No cabe con margen razonable → RAG.
    if context_usage > 0.7:
        return Architecture.PURE_RAG
    # Cabe pero cambia muy a menudo → RAG (evita re-inyectar todo).
    if corpus.update_frequency_days < 7:
        return Architecture.PURE_RAG
    # Cabe y es muy estable → CAG puro sigue siendo válido.
    if corpus.update_frequency_days > 90 and context_usage < 0.3:
        return Architecture.PURE_CAG
    # Resto: híbrido.
    return Architecture.HYBRID_CAG_RAG
```

**Fine-tuning** no aparece en la función porque **no es una alternativa a RAG**: es una
capa que se suma encima (de RAG o de CAG) cuando hay limitaciones que no se resuelven con
mejor retrieval. Casos típicos: estilo de respuesta muy específico de la empresa,
terminología propia, formato estructurado que el modelo no respeta. Regla de oro: si la
respuesta del modelo base sobre fragmentos correctamente recuperados ya es buena, no hace
falta fine-tuning. **Lo que nunca funciona es usar fine-tuning como sustituto de un
retrieval mal diseñado** (le enseñas al modelo a memorizar lo que debería estar
buscando).

## 1.6 El caso del Proyecto 2 sobre el árbol

| Eje | Valor en el Proyecto 2 | Empuje |
|---|---|---|
| **Volumen** | Crece linealmente; cientos de docs al año | → RAG |
| **Frecuencia** | Alta: reuniones semanales, presupuestos mensuales | → RAG |
| **Trazabilidad** | Crítica: una estimación de 80.000 € necesita precedentes que la justifiquen | → RAG |
| **Sensibilidad** | Alta: info comercial confidencial, nombres de cliente, condiciones contractuales | → RAG |

Tres de los cuatro ejes empujan directamente a RAG: la elección está justificada. Pero
hay un matiz: partes del contexto **sí son pequeñas y estables** (glosario de tecnologías,
plantillas de presupuesto, rangos de tarifas oficiales). Para esas, el CAG tradicional
sigue siendo la mejor opción (más simple, barato y predecible que vectorizarlas). Por eso
el árbol contempla la opción **híbrida**: el sistema final del Proyecto 2 tendrá una capa
de CAG conviviendo con la de RAG, **no una sustituyendo a la otra**.

## 1.7 Trade-offs honestos del Artículo 1

- **El coste oculto de la trazabilidad.** Citar fuentes no es gratis: exige preservar
  metadatos en cada chunk (origen, página, fecha, autor), propagarlos por todo el
  pipeline, devolverlos al backend y construir UI que los presente. Si tu producto puede
  permitirse no citar, el sistema se simplifica notablemente.
- **El coste real de operar RAG.** Las comparativas CAG vs RAG suelen ser tramposas. RAG
  añade el coste de embeddings (uno por chunk), de la BBDD vectorial, de operar el
  pipeline de indexación y de las re-indexaciones. Sumado todo, **RAG puede ser más caro
  que CAG** en corpus que caben en el context window. La elección no se hace por coste; se
  hace por **viabilidad y funcionalidad**.
- **El CAG no muere, cambia de papel.** El sistema final no es "RAG en lugar de CAG", sino
  **"RAG además de CAG"**: coexisten el contexto estático del sistema (instrucciones,
  esquemas, glosarios, inyectado como en el Módulo 2) y el contexto recuperado
  dinámicamente (vía RAG).

---

# PARTE 2 — Auditoría e inventario de datos empresariales

## 2.1 El antipatrón: vectorizar primero, mirar después

El reflejo del ingeniero senior es ponerse manos a la obra. En RAG ese reflejo tiene un
**coste asimétrico**: los errores de saltarse la auditoría no aparecen el día 1, aparecen
el día 60, cuando ya hay un pipeline construido sobre supuestos que nadie verificó.

Los tres **modos de fallo** típicos del antipatrón:

1. **Mezcla silenciosa de versiones.** El corpus contiene dos versiones contradictorias
   del mismo presupuesto (la propuesta inicial y la firmada con cambios) y el RAG recupera
   la equivocada porque no hay metadato que las distinga.
2. **Fuentes podridas.** Documentos que parecen válidos pero contienen información obsoleta
   (políticas que cambiaron, tarifas que se actualizaron) y generan respuestas seguras a
   preguntas para las que la verdad es la contraria.
3. **Gaps invisibles.** El sistema responde bien donde hay datos, pero genera información
   plausible y falsa donde no los hay, porque nadie supo decir que esa categoría de
   pregunta no está cubierta.

Los tres tienen la misma raíz: el equipo nunca se sentó a mirar lo que había antes de
procesarlo. **La auditoría no es un trámite previo al trabajo real; es el trabajo real.**

## 2.2 Inventario de fuentes: el censo de lo que tienes

El primer paso operativo es construir un **censo**: una lista factual y verificable de qué
fuentes existen, dónde viven, quién las mantiene, qué formato tienen y qué volumen ocupan.
Campos mínimos por fuente:

- **Nombre lógico** — identificador estable (`historical_budgets`, no "los presupuestos
  viejos del Drive").
- **Localización física** — path o URL exacto, incluido el sistema de almacenamiento.
- **Owner técnico** — responsable de que la fuente exista y sea accesible.
- **Owner de negocio** — responsable del contenido (a quién preguntas cuando es ambiguo).
- **Formato físico** — JSON, CSV, PDF, DOCX, TXT, fila de BBDD, respuesta de API.
- **Volumen actual** — nº aproximado de registros y tamaño en disco.
- **Método de acceso** — FTP, API, descarga manual, query SQL.
- **Periodicidad declarada** — cada cuánto cambia *oficialmente*.
- **Periodicidad observada** — cada cuánto cambia *realmente*.

La pareja **declarada vs observada** revela problemas que nadie había mirado: una fuente
que oficialmente se actualiza mensualmente pero cuya última modificación es de hace siete
meses **no es una fuente mensual; es una fuente abandonada que alguien todavía cree viva**.

El censo no se hace de cabeza: se ejecuta un script de inspección (p.ej. una dataclass
`FilesystemSourceFacts` con `name`, `path`, `file_count`, `total_size_mb`,
`latest_modified`, `formats_detected`) y se completan manualmente los campos subjetivos
que el script no puede deducir.

## 2.3 Evaluación de calidad por dimensiones

"Datos abundantes" no es lo mismo que "datos buenos". La evaluación se articula sobre
**cuatro dimensiones** (escala 1–5):

- **Completitud.** ¿Cuántos registros tienen todos los campos esperados? ¿Cuántos tienen
  `total_amount` como string en lugar de número, o vacío?
- **Consistencia.** ¿El mismo concepto se representa igual? Si `currency` toma valores
  normalizados (`EUR`) o variantes (`euros`, `€`, `eur`). Las inconsistencias son veneno
  para el chunking y el retrieval.
- **Actualidad.** ¿Qué fecha tiene el último dato relevante? Una fuente con `last_modified`
  de hace dos años probablemente no es una fuente viva.
- **Fiabilidad.** ¿La fuente es autoritativa o derivada? Una hoja rellenada a mano cada
  trimestre es menos fiable que el output de un sistema transaccional con validación.

```python
class QualityScore(IntEnum):
    UNUSABLE = 1
    POOR = 2
    ACCEPTABLE = 3
    GOOD = 4
    EXCELLENT = 5

@dataclass
class QualityAssessment:
    completeness: QualityScore
    consistency: QualityScore
    actuality: QualityScore
    reliability: QualityScore
    notes: str

    @property
    def is_rag_ready(self) -> bool:
        # Regla deliberadamente estricta: NO se promedian las dimensiones.
        return all(
            score >= QualityScore.ACCEPTABLE
            for score in (self.completeness, self.consistency,
                          self.actuality, self.reliability)
        )
```

**El promedio engaña.** Una fuente con `completeness=5` y `reliability=1` no es de "calidad
3": es una fuente cuyos datos están completos pero pueden ser mentira, que es lo peor para
RAG. Las dimensiones **no se compensan**; cada una es condición necesaria.

## 2.4 Linaje y context erosion

Hay un quinto criterio que opera en otro plano: el **linaje** (*lineage*), el rastro del
origen y las transformaciones de un dato. En business intelligence es buena práctica; en
RAG es una **condición de utilidad**. Cuando el RAG presenta un fragmento como evidencia,
el usuario necesita poder verificar la procedencia: ¿de qué documento viene?, ¿cuándo se
generó?, ¿qué nivel de autoridad tiene (propuesta inicial, revisada, contrato firmado)?

El fenómeno opuesto, que destruye el linaje, se llama **context erosion** (erosión de
contexto): la pérdida progresiva de contexto a medida que el dato se mueve entre sistemas.

```
ERP record BUDGET-2024-0315   (todos los metadatos intactos)
  → presupuesto_v3.pdf        (exportado a Drive, solo metadatos de subida)
  → cliente_acme_2024.pdf     (descargado y renombrado, solo nombre + fecha)
  → cliente_acme.txt          (extracción de texto, sin metadatos)
```

La información sigue ahí, pero **el contexto que la hacía interpretable se ha evaporado**.
Combatir la context erosion es la razón fundamental por la que el **catálogo** es un
artefacto necesario: es el sitio donde se preserva, por construcción y de forma
versionada, todo el contexto que se perdería si confías solo en los nombres de fichero.

## 2.5 El catálogo mínimo viable como YAML versionado

Toda la información recolectada (censo, calidad, decisiones, linaje) tiene que vivir en
algún sitio. Para proyectos de tamaño medio: **en el propio repositorio, como un YAML
versionado** (`data_catalog.yaml`). Estructura plana por fuente:

```yaml
version: 1
last_audited: "2026-05-15"
sources:
  - name: historical_budgets
    description: Closed project budgets since 2020 stored as JSON.
    location: drive://AI-Eng/budgets/
    owner_technical: data-platform@company.com
    owner_business: ops-lead@company.com
    format: json
    volume: { records: 80, size_mb: 12.4 }
    refresh:
      declared: monthly
      observed_last_update: "2026-04-15"
      observed_lag_days: 3
    quality: { completeness: 4, consistency: 3, actuality: 5, reliability: 5 }
    sensitivity:
      contains_pii: true
      pii_types: [client_names, hourly_rates, internal_margins]
      access_restrictions: internal-only
    lineage:
      upstream: erp-finance-module
      transformations: [export_to_json_quarterly]
    decision: include   # include | exclude | review
    notes: >
      Budgets prior to 2022 use a legacy schema. Filter them out during
      ingestion until the migration script is rerun.
```

El catálogo **es un artefacto de software, no documentación muerta**: cualquier código que
toque las fuentes debería leer este YAML al arrancar para saber qué procesar, qué excluir
y qué metadatos propagar. Por eso necesita un **loader tipado** (modelos Pydantic:
`IngestionDecision`, `Volume`, `Refresh`, `Quality`, `Sensitivity`, `Lineage`,
`CatalogSource`, `DataCatalog` con `included_sources()` y `load_catalog()`).

Tres ventajas de tenerlo como código tipado:

1. **Validación automática** — un PR que rompe el schema no llega a producción.
2. **Acoplamiento explícito** — el pipeline itera sobre `catalog.included_sources()` y
   propaga `lineage.upstream` y `sensitivity` como metadatos de cada chunk.
3. **Trazabilidad de cambios** — el `git log` del YAML es el historial de cómo evoluciona
   el corpus, con quién decidió incluir/excluir cada fuente y por qué.

## 2.6 El reporte de auditoría como deliverable

Sobre el catálogo se monta una pieza opcional pero recomendable: un **reporte de
auditoría** que se genera automáticamente (`generate_audit_report(catalog) -> str`,
formateado a Markdown) y sirve para comunicar el estado del corpus a quien no lee YAML
(producto, comité ejecutivo, cliente). Generarlo en cada cambio del catálogo (en CI,
idealmente) convierte la auditoría en una práctica viva, no en una entrega de una sola
vez. **El catálogo no es un documento que se escribe al principio y se olvida; es un
artefacto que respira con el proyecto.**

## 2.7 Trade-offs honestos del Artículo 2

- **Catálogo formal vs YAML en repo.** Existen plataformas profesionales (Atlan, DataHub,
  Collibra, Microsoft Purview) con descubrimiento automático, linaje a nivel de columna y
  governance. Tienen sentido con cientos de fuentes y un equipo dedicado. Para un proyecto
  de una o dos docenas de fuentes, el YAML versionado es lo correcto **hasta** que el
  número crece o aparece un mandato regulatorio. Migrar de YAML a plataforma es trivial;
  saltar directo a la plataforma suele resultar en una herramienta cara y vacía.
- **Auditoría exhaustiva vs suficiente para arrancar.** Las fuentes son móviles: lo que
  documentes hoy estará desactualizado en dos meses. La auditoría inicial debe cubrir solo
  las fuentes del **primer release**, no todas las de la organización. El catálogo crece
  con el proyecto, no antes que él.
- **Decidir qué dejar fuera deliberadamente.** Falacia común: "toda fuente disponible debe
  usarse". En RAG es peligrosa porque las fuentes malas no se manifiestan como ruido
  aleatorio (fácil de detectar) sino como **respuestas seguras a información incorrecta**.
  Excluir fuentes dejando registrado por qué es **higiene profesional**. El
  `rate_card_2024.xlsx` desactualizado del ejemplo es el caso típico: oficialmente es la
  fuente de la verdad, pero incluirlo introduciría errores sistemáticos. Excluirlo no es
  desidia; es disciplina arquitectónica.

---

# PARTE 3 — Pipeline de extracción multi-formato

Con el catálogo cerrado, toca convertir el contenido físico de cada fuente en texto
procesable. El Proyecto 2 se enfrenta a **cinco familias de formato**: JSON (presupuestos),
TXT (transcripciones), XLSX (tarifarios), DOCX (plantillas de propuesta), PDF (contratos y
propuestas con maquetación). Cada una trae su propia maldición técnica.

La tentación es instalar `unstructured`, llamar a `partition()` y dar el problema por
resuelto. Es la respuesta correcta a corto plazo y la incorrecta a medio: delegar todo a
una librería sin pensar en arquitectura es exactamente cómo se construyen los pipelines
que dos meses después nadie entiende. El patrón opuesto: **arquitectura modular donde cada
formato se trata con la herramienta correcta y todo confluye en un contrato común**.

## 3.1 El contrato común: el `Document` canónico

Antes de elegir un parser, hay que cerrar qué tiene que producir el subsistema `ingest/`
para el resto del servicio IA. La respuesta es un objeto canónico (en la literatura
aparece como `Document`, `Chunk` o `Passage`) con dos campos esenciales: el **contenido
textual** y los **metadatos**.

```python
class DocumentMetadata(BaseModel):
    """Metadatos que viajan con cada documento por el pipeline."""
    source_name: str        # coincide con una entrada de data_catalog.yaml
    source_location: str     # path o URL original
    ingested_at: datetime    # (los tres primeros vienen del catálogo, obligatorios)

    document_id: str
    document_title: Optional[str] = None
    document_created_at: Optional[datetime] = None
    document_author: Optional[str] = None

    page_number: Optional[int] = None     # formatos paginados
    section_title: Optional[str] = None   # formatos estructurados
    contains_pii: bool = False
    extra: dict = Field(default_factory=dict)

class Document(BaseModel):
    """Salida canónica del subsistema ingest. Todo parser produce esto."""
    content: str
    metadata: DocumentMetadata
```

Dos virtudes del modelo: **homogeneidad del contrato downstream** (el módulo de chunking
no sabe ni necesita saber si el `Document` viene de un PDF escaneado o de un JSON; procesa
`content` y propaga `metadata`) y **trazabilidad por construcción** (cada documento sabe
de qué fuente viene, dónde estaba y, cuando el formato lo permite, en qué página o
sección). El campo `extra` como diccionario abierto es una válvula de escape consciente.

## 3.2 Arquitectura modular del subsistema `ingest/`

Tres capas que separan responsabilidades por tipo de problema:

```
servicio_ia/
└── ingest/
    ├── loaders/        # acceso físico a fuentes
    │   ├── filesystem.py
    │   ├── drive.py
    │   └── http.py
    ├── parsers/        # extracción por formato
    │   ├── json_parser.py
    │   ├── pdf_parser.py
    │   ├── docx_parser.py
    │   ├── xlsx_parser.py
    │   └── txt_parser.py
    ├── normalizers/    # homogeneización a Document
    │   └── canonical.py
    ├── catalog.py      # loader del data_catalog.yaml (Artículo 2)
    └── orchestrator.py # pega todo y produce Document[]
```

- **Loaders** — "cómo llego al fichero". Saben de paths, URLs HTTP, auth de Drive, claves
  de S3. No saben qué hay dentro; lo entregan como bytes o stream. (Un mismo formato puede
  vivir en Drive, S3 o disco; no queremos triplicar el parser de PDF por ubicación.)
- **Parsers** — "qué hay dentro". Reciben bytes, eligen la librería según el formato y
  producen una **representación intermedia** específica del parser (un DataFrame de pandas
  para Excel, una lista de elementos para PDF). **No es el `Document` canónico todavía.**
- **Normalizers** — "cómo convierto la salida de mi parser al contrato canónico". Capa fina
  que toma la representación intermedia y la convierte en `Document`, propagando metadatos
  del catálogo.

¿Por qué tres capas y no dos? **Testabilidad.** Los parsers son lógica compleja dependiente
de librerías pesadas; testearlos contra el contrato canónico obligaría a rellenar metadatos
del catálogo en cada test. Separar la normalización permite testear parsers contra su
representación intermedia (fácil de mockear) y normalizers contra el contrato canónico
(también fácil). Cada test queda enfocado.

## 3.3 Estrategias de parsing por formato

| Formato | Maldición | Estrategia |
|---|---|---|
| **JSON** | Parece fácil porque ya tiene estructura | No extraer texto: decidir qué representación textual entra al RAG. `json.dumps()` genera embeddings ruidosos (mezcla claves técnicas con valores semánticos). **Mejor: renderizar a markdown estructurado** — claves importantes a títulos, valores como prosa. |
| **TXT** | Esconde una trampa: las transcripciones no son texto homogéneo | Las nuevas tienen `[hh:mm:ss] Speaker: ...`; las viejas son heterogéneas. Tratarlas como bolsa de texto pierde **quién dijo qué**. Parser que detecta el formato y produce turnos con metadatos `speaker` y `timestamp`. |
| **XLSX** | El más traicionero: parece tabular y rara vez lo es | Celdas combinadas, fórmulas, múltiples tablas por hoja, hojas ocultas. Extraer la tabla principal con `openpyxl`/`pandas.read_excel()` a markdown. **Regla: si es tabla pura → tabla markdown; si tiene estructura compleja → no debería estar en el corpus o requiere conversión manual.** |
| **DOCX** | Sorprendentemente amable | `python-docx` recorre párrafos, tablas y headings con API limpia. Los DOCX modernos tienen estructura semántica explícita. Extraer **secciones por heading** (`Alcance`, `Entregables`, `Cronograma`) → un `Document` por sección con el heading como `section_title`. |
| **PDF** | El infierno: es formato de presentación, no de contenido | La estructura semántica es implícita (posiciones, fuentes, tamaños). Tres opciones ↓ |

Opciones para PDF:

1. **`pypdf` / `pdfplumber`** — texto plano: rápido y barato, pierde tablas, columnas y
   estructura.
2. **`pymupdf` (alias `fitz`)** — mejor manejo de layout, imágenes y bounding boxes. Buena
   opción cuando el PDF es texto digital limpio.
3. **`unstructured` con `strategy="hi_res"`** — usa visión por ordenador para detectar
   tablas, encabezados y secciones. Correcta cuando hay tablas relevantes o escaneos que
   requieren OCR. **La más lenta y cara con diferencia.**

Regla del Proyecto 2: `pypdf` por defecto para documentos digitales; `unstructured` con
`hi_res` solo cuando se detecta que el PDF contiene tablas o es escaneado. **La decisión se
toma una vez por fuente en el catálogo, no por documento.**

## 3.4 El parser universal con `unstructured` como navaja suiza

Alternativa al patchwork anterior: usar `unstructured` para todo. Su `partition()` detecta
el formato y devuelve una lista de `Element` heterogéneos (`Title`, `NarrativeText`,
`Table`, `ListItem`) con metadatos de localización.

- **Ventajas reales:** unifica el interface, soporta 20+ formatos, modelos de detección de
  estructura sorprendentemente buenos.
- **Costes:**
  - **Peso** — `unstructured[all-docs]` mete cientos de MB en la imagen Docker (Tesseract,
    modelos de detección, PyTorch).
  - **Latencia y coste** — `hi_res` es un orden de magnitud más lento que un parser nativo
    para PDFs simples.
  - **Opacidad** — cuando algo va mal, depurar es difícil porque buena parte del trabajo lo
    hace un modelo neuronal que no explica sus decisiones.

Recomendación operativa: **parsers nativos para formatos de estructura predecible** (JSON,
TXT, XLSX simple, DOCX), **`unstructured` reservado para PDF cuando lo necesita** (tablas,
escaneo) y como fallback opcional para formatos exóticos.

## 3.5 Propagación de metadatos a través del pipeline

Los metadatos que viajan con cada documento permiten al RAG hacer citas. Su fuente es
**triple**:

- **Metadatos del catálogo** — conocidos antes de tocar el documento (nombre lógico, owner,
  sensibilidad PII, decisión de inclusión). Vienen de `data_catalog.yaml`, uniformes para
  toda la fuente.
- **Metadatos del parser** — conocidos después de procesar (título de un encabezado, autor,
  fecha de creación, número de página, sección).
- **Metadatos del pipeline** — conocidos en el momento del procesamiento (`ingested_at`,
  versión del parser, configuración usada). Útiles para depuración y reproducibilidad.

El **orchestrator** combina las tres fuentes. Tres detalles del diseño:

```python
class Parser(Protocol):  # structural typing, no herencia: más flexible y testeable
    supported_formats: set[str]
    def parse(self, content: bytes, source_hint: str) -> list[Document]: ...

def ingest_source(source, loader, parsers) -> list[Document]:
    if source.decision != IngestionDecision.INCLUDE:
        return []  # respeta la decisión del catálogo (exclude/review no se procesan)
    parser = parsers.get(source.format)
    # ... por cada fichero: el parser rellena content + metadatos que conoce,
    # y el orchestrator SOBRESCRIBE source_name/location con el valor canónico
    # del catálogo (si un parser lo falsifica, gana el catálogo). Defensa en profundidad.
```

1. `Parser` como **Protocol** (structural typing) en lugar de clase abstracta: más
   flexible, se testea mejor.
2. El orchestrator **respeta la decisión del catálogo**: `exclude`/`review` no se procesan.
3. Los metadatos del catálogo se aplican **después** del parser: si un parser intentara
   falsificar `source_name`, el orchestrator lo sobrescribe con el valor canónico.

## 3.6 Trade-offs honestos del Artículo 3

- **Parsers nativos vs `unstructured` universal.** No es cuestión de tribu sino de
  contexto: <5-6 formatos predecibles → nativos (rápidos, baratos, fáciles de depurar);
  docenas de formatos heterogéneos → `unstructured` (evita reinventar veinte ruedas).
- **`hi_res` vs `fast` en PDF.** Usar `hi_res` para todo "por seguridad" es comprensible y
  peligroso: sobre 100 PDFs puede tardar y costar 20× más, mientras que sobre los 90 que
  son texto digital limpio no aporta nada. Clasificar los PDFs en el catálogo (digital
  limpio, digital con tablas, escaneado) es trabajo manual de una vez; el ahorro es
  continuo.
- **Pérdida de información estructural aceptable.** Hay información que no sobrevive al
  pipeline (imágenes embebidas en DOCX, comentarios de Word, anotaciones en márgenes de
  PDF, formato condicional de Excel). Para un RAG de estimación es ruido prescindible; para
  un RAG de revisión legal de contratos, las anotaciones serían críticas. Lo inaceptable es
  perder información **por descuido en lugar de por diseño**.

---

# PARTE 4 — Limpieza, normalización y validación de datos

Los `Document` que produce `ingest/` cumplen el contrato Pydantic: tienen `content` no
vacío y `metadata` con los campos requeridos. Pero ese es solo el **contrato de forma**. No
dice nada del **contrato de contenido**.

Dos `Document` pueden cumplir Pydantic y ser radicalmente incompatibles para RAG:

- `client_name: "ACME Corp."` y `client_name: "Acme Corp"` → válidos individualmente, pero
  los embeddings los tratan como entidades distintas y el retrieval falla en silencio.
- `total_amount: -50000` → pasa la validación de tipo (es un número) y rompe cualquier
  análisis aritmético.
- Una fecha `"15/03/2024"` y otra `"2024-03-15"` → ambas strings válidas, radicalmente
  diferentes para cualquier filtrado temporal.

Pydantic es la **primera línea de defensa, no la última**. Este artículo monta la segunda:
**la capa de limpieza y validación que garantiza el contrato de contenido antes del
embedding**.

## 4.1 Cuatro familias de "suciedad" en datos para RAG

1. **Heterogeneidad de formato.** La misma cosa escrita de N maneras: fechas
   (`15/03/2024`, `2024-03-15`, `March 15 2024`), monedas (`EUR`, `eur`, `€`, `euros`),
   identificadores (`ACME`, `Acme Corp.`, `acme-corp`). Veneno: los embeddings tratan cada
   variante como un token distinto → dos fragmentos del mismo cliente acaban en regiones
   distantes del espacio vectorial.
2. **Duplicados con divergencias.** El mismo registro existe dos veces con valores distintos
   (`total: 80000` en el JSON del ERP, `total: 82500` en la copia manual). El RAG recupera
   el que el chunker indexó primero, sin saber cuál es correcto. Diagnosticar esto en
   producción lleva semanas porque el sistema no se rompe; da respuestas inconsistentes que
   "parecen ruido del LLM".
3. **Valores nulos disfrazados.** Campos que parecen rellenados pero no contienen
   información: `"N/A"`, `"-"`, `"unknown"`, `"TBD"`, `"pendiente"`, cadena vacía, un solo
   espacio. Técnicamente válidos (son strings), pasan la validación de tipo, se vectorizan
   como contenido real. El RAG aprende a "recuperar" estos valores como si tuvieran
   significado.
4. **Valores fuera de rango.** `total: -50000`, fechas de fin anteriores a las de inicio,
   porcentajes >100, `hours_estimated` en millones. Impacto asimétrico: rara vez se
   recuperan (los embeddings los aíslan), pero cuando lo hacen generan **respuestas con
   confianza alta sobre afirmaciones absurdas**, que son las que más caro pagan los
   stakeholders en credibilidad.

Todas requieren la misma decisión arquitectónica: **un punto único del pipeline donde se
aplican las reglas, con un contrato explícito de qué pasa y qué no pasa.**

## 4.2 Dónde colocar la capa de limpieza

La tentación es resolver cada problema donde se descubre (el chunker detecta un campo
vacío, el embedder un duplicado, el retriever un valor fuera de rango). **Es exactamente lo
que no hay que hacer.** Cuando la limpieza está repartida:

- **Las reglas dejan de ser auditables** — no hay un sitio donde decir "estos son nuestros
  invariantes de datos".
- **Los tests se vuelven imposibles** — testear el chunker requiere mockear validaciones
  que pertenecen a otra capa.
- **El sistema queda sin un único punto donde un fallo pueda detenerlo** — un registro
  malformado se cuela y aparece seis semanas más tarde.

La capa de limpieza tiene que ser un **módulo separado**. Recordando la arquitectura del
Artículo 3 (`loaders → parsers → normalizers → Document`), su posición natural es **entre
el parser y el normalizer**: el parser produce su representación intermedia, esa
representación pasa por la capa de limpieza, y solo entonces se convierte al `Document`
canónico. Para formatos tabulares (los presupuestos JSON), la representación intermedia es
un `DataFrame` de pandas. Los no tabulares (PDF, DOCX, TXT) no escapan a la validación: sus
representaciones son listas de elementos o texto, y sobre ellas se aplican técnicas
distintas (regex, validación de encoding, longitud mínima, detección de placeholders).

## 4.3 Limpieza con pandas sobre la representación intermedia

```python
NULL_PLACEHOLDERS = {"", "n/a", "na", "-", "--", "unknown", "tbd", ...}

def clean_budget_records(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    # 1. Nulos disfrazados → NaN real
    out["client_name"] = (out["client_name"].astype(str).str.strip().str.lower()
        .where(lambda s: ~s.isin(NULL_PLACEHOLDERS), other=pd.NA))
    # 2. Normalización de moneda
    currency_map = {"eur": "EUR", "euros": "EUR", "€": "EUR", "usd": "USD", "$": "USD"}
    out["currency"] = (out["currency"].astype(str).str.strip().str.lower()
        .map(currency_map).fillna(out["currency"]))
    # 3. Parsing de fechas con fallback explícito
    out["signed_at"] = pd.to_datetime(out["signed_at"], errors="coerce", utc=True)
    # 4. Coerción numérica (string "80000" → 80000.0)
    out["total_amount"] = pd.to_numeric(out["total_amount"], errors="coerce")
    # 5. Dedup por hash de contenido: quedarse con la última versión por budget_id
    out = out.sort_values("signed_at").drop_duplicates(subset=["budget_id"], keep="last")
    return out
```

Tres detalles del diseño:

1. **Cada paso es estrechamente acotado** — hace una cosa y se mueve. Facilita testear en
   aislamiento.
2. **El paso 5 (dedup)** ataca la familia "duplicados con divergencias". La regla "quédate
   con el último según `signed_at`" debe ser una **decisión consciente del equipo,
   documentada en el catálogo**.
3. **Las coerciones permisivas** (`errors="coerce"`) convierten valores inválidos en `NaN`
   en lugar de tirar excepción. Esto separa la limpieza de la validación: aquí
   transformamos lo que se puede transformar; la validación posterior decide qué hacer con
   los `NaN`.

Esta función **no decide nada**: deja registros con campos vacíos, valores fuera de rango y
fechas no parseables como `NaT`. La decisión de qué pasa con esos registros es de la capa
de validación.

## 4.4 Pandera como contrato de datos

**Pandera** es a los DataFrames lo que Pydantic a las instancias individuales: "este
DataFrame cumple este schema columna a columna y fila a fila, o produce un reporte detallado
de qué filas fallan y por qué".

```python
class BudgetRecord(DataFrameModel):
    budget_id: Series[str] = Field(str_matches=r"^BUDGET-\d{4}-\d{4}$")
    client_name: Series[str] = Field(nullable=False, str_length={"min_value": 2, "max_value": 200})
    total_amount: Series[float] = Field(ge=0, le=10_000_000, nullable=False)
    currency: Series[str] = Field(isin=["EUR", "USD", "GBP"])
    signed_at: Series[pd.Timestamp] = Field(nullable=False, le=datetime.now(timezone.utc))
    status: Series[str] = Field(isin=["draft", "signed", "rejected"])

    class Config:
        strict = True    # rechaza columnas no declaradas
        coerce = False   # la limpieza ya hizo las coerciones
        ordered = False

    @pa.dataframe_check
    def positive_amount_for_signed(cls, df: pd.DataFrame) -> Series[bool]:
        # Regla cross-column: status='signed' implica total_amount > 0.
        return ~((df["status"] == "signed") & (df["total_amount"] == 0))
```

Tres elementos del schema:

1. **Checks de campo** (`ge=0`, `le=10_000_000`, `str_matches`) — cada uno expresa un
   **invariante de negocio**. La forma del `budget_id` no es estética; es un contrato con el
   sistema upstream.
2. **Checks cross-column** (`@pa.dataframe_check`) — reglas que relacionan varias columnas
   ("si el estado es `signed`, el total no puede ser cero"). Detectan las inconsistencias
   más sutiles; un schema solo-Pydantic no puede expresarlas.
3. **Configuración** — `strict=True` rechaza columnas no declaradas (defensa contra cambios
   silenciosos del parser); `coerce=False` asume que la limpieza previa ya coercionó
   (separación de responsabilidades clara).

El contrato Pandera es **una pieza viva**: cuando se acepta una nueva moneda o cambia el
límite máximo, el cambio se hace en este fichero y solo en este fichero, queda versionado
en git, y todo el pipeline downstream lo respeta. Es el equivalente al `data_catalog.yaml`
para datos.

## 4.5 La estrategia de fallo: reparar, cuarentena, descartar

Cuando una fila falla la validación, hay tres respuestas, y la decisión depende del tipo de
fallo. La política tiene que ser **explícita y documentada**:

- **Reparar automáticamente** — cuando el fallo es recuperable sin pérdida semántica. Una
  fecha `"15/03/2024"` que sí parsea con `dayfirst=True`; un `"euros"` que claramente debe
  ir a `"EUR"`. Se resuelve con una pasada adicional de limpieza, **sin intervención
  humana**.
- **Mandar a cuarentena** — cuando el fallo es grave pero el registro podría ser útil tras
  revisión. Un `client_name` nulo con el resto del registro completo; un `total_amount`
  ligeramente por encima del límite (¿proyecto excepcional legítimo o typo?). **No entran
  al RAG, pero se preservan** en una tabla separada con su motivo, accesibles para que un
  humano decida.
- **Descartar** — cuando el fallo indica contaminación clara y no aporta valor. Un
  `budget_id` que no cumple el patrón (artefacto de migración mal hecha); un total negativo
  o cien veces el límite. **Se eliminan con log detallado** pero sin reserva.

```python
@dataclass
class ValidationResult:
    valid: pd.DataFrame
    quarantined: pd.DataFrame
    discarded: pd.DataFrame
    report: dict

def validate_with_policy(df, schema) -> ValidationResult:
    try:
        valid = schema.validate(df, lazy=True)   # lazy=True: recoge TODOS los errores
        return ValidationResult(valid, pd.DataFrame(), pd.DataFrame(), {...})
    except pa.errors.SchemaErrors as exc:
        failure_cases = exc.failure_cases
        # Política de descarte: fallos estructurales que señalan contaminación.
        is_discard = failure_cases["check"].isin(["str_matches", "ge(0)", "le(10000000)"])
        # ... resto → cuarentena. Devuelve valid / quarantined / discarded + report.
```

Dos detalles:

1. **`lazy=True`** — en lugar de fallar en el primer error, Pandera recoge **todos** los
   errores del DataFrame y los devuelve juntos. Es lo que permite la política diferenciada
   por tipo de fallo; sin `lazy=True` solo conoceríamos el primer error y la política sería
   ciega.
2. **El resultado siempre incluye el `report`** — métricas para observabilidad (cuántos
   válidos, cuántos en cuarentena, qué tipos de fallo predominan). Esa información es la que
   **alerta cuando una fuente empieza a degradarse**, mucho antes de que el degradado llegue
   al RAG.

## 4.6 Trade-offs honestos del Artículo 4

- **Pandera vs Great Expectations.** Pandera es **ligera, integrada en código Python,
  declarativa**: el schema vive con tu código y se versiona con él. Great Expectations es
  **más ambiciosa**: datadocs (documentación HTML auto-generada), profiling automático,
  integración nativa con Airflow/Dagster, pero más pesada de operar. Para el tamaño del
  Proyecto 2, Pandera es lo correcto (cero overhead de infraestructura). Great Expectations
  tiene sentido cuando el sistema escala a docenas de pipelines con stakeholders no
  técnicos.
- **Strict mode en producción vs permisividad en desarrollo.** El instinto correcto es el
  opuesto al esperado: **el schema debe ser estricto desde el primer día**, y lo que se
  relaja es la **política ante fallos**, no el contrato. En desarrollo, mandar a cuarentena
  en lugar de descartar permite ver los datos problemáticos sin romper el pipeline; en
  producción, descartar evita contaminar el corpus. Pero el contrato de qué es válido es el
  mismo. Cuando el contrato es laxo en desarrollo, los problemas aparecen el día del
  despliegue.
- **Cuánto normalizar sin perder señal.** Normalizar agresivamente es peligroso: pasar todos
  los nombres a minúsculas resuelve "ACME Corp" vs "acme corp" pero borra la diferencia
  entre "Apple" (empresa) y "apple" (fruta). La regla heurística: **normalizar con el
  bisturí, no con la motosierra**. Primero los casos donde la heterogeneidad es claramente
  accidental (mayúsculas en monedas, espacios trailing, separadores de fecha); dejar para
  una segunda iteración (o nunca) los casos donde podría borrar señal semántica.

---

# PARTE 5 — PII, anonimización y GDPR en el pipeline de ingest

El corpus ya pasó por inventario, extracción y validación. Pero contiene, sin excepción,
**información personal y comercial sensible**: nombres de clientes en transcripciones,
correos en presupuestos, teléfonos de interlocutores, identificadores internos de proyecto
que revelan estructura organizativa, condiciones contractuales que legal pidió no
compartir.

## 5.1 El problema real: filtración semántica vía RAG (para cualquiera)

Hay una intuición común que conviene desmontar: muchos equipos asumen que el **control de
acceso** al sistema (autenticación, autorización, ACLs en la aplicación) basta para proteger
esos datos. Funciona en bases de datos tradicionales. **No funciona en RAG**, y el motivo es
estructural.

Piénsalo así: en una base de datos relacional, para robar la columna `email` de la tabla
`clients` necesitas formular una query SQL específica que apunte a esa columna. Si está
protegida por permisos, no hay query que la devuelva. En RAG el ataque es **indirecto**: el
usuario no consulta tablas, hace **preguntas en lenguaje natural**. El sistema busca
semánticamente, recupera los chunks más relevantes y se los pasa al modelo. Si los chunks
contienen el dato sensible (literalmente, en el texto), el modelo lo usa en su respuesta.
**No hay un nivel de permisos en el vector que pueda ocultarlo, porque el vector no sabe qué
es sensible.**

Por eso la protección tiene que ocurrir **antes** del embedding, no como filtro en la
respuesta.

## 5.2 Los tres modos de filtración

1. **Filtración directa.** La más obvia. *"¿Qué clientes nos han contratado proyectos de
   migración a cloud?"* → el RAG devuelve "Banco Sabadell, Inditex y Repsol" porque esos
   nombres están literalmente en los chunks. Trivial de explotar y trivial de prevenir si la
   anonimización está en su sitio.
2. **Filtración por agregación.** Más sutil. Cada query parece inocua, pero el atacante las
   combina: *"¿Qué proyectos completamos en 2024?"*, *"¿Cuál fue el más caro?"*, *"¿En qué
   sector?"*, *"¿Qué tecnologías usamos?"*. Cada pregunta devuelve datos parciales; el
   atacante los une en una imagen completa. Defenderse exige pensar en términos de
   **superficie de información agregada**, no de chunks individuales.
3. **Filtración por inferencia.** La más peligrosa porque ocurre **incluso después de la
   anonimización ingenua**. Si reemplazas "Juan García, CEO de Acme Corp" por "[PERSON], CEO
   de [ORG]", parece protegido. Pero el contexto que rodea al token sigue ahí: el sector,
   las fechas, los importes, la geografía. Combinado con metadatos del catálogo y del
   parser, puede bastar para que un atacante con conocimiento del dominio identifique al
   individuo. La defensa no es solo anonimizar, sino **reducir la combinatoria de pistas que
   rodean al individuo**.

Las tres familias comparten una característica: **ninguna requiere acceso administrativo**.
Bastan credenciales legítimas de usuario y preguntas en lenguaje natural.

## 5.3 El marco GDPR mínimo aplicado al pipeline

GDPR es la regulación europea que gobierna el tratamiento de datos personales. Cuatro
conceptos que cualquier AI Engineer en la UE necesita interiorizar:

- **Datos personales.** Definición deliberadamente amplia: cualquier información que pueda
  identificar, directa o indirectamente, a una persona física. Los nombres/emails/teléfonos
  son obvios; menos obvios son los **identificadores indirectos** (IP, cookie, número de
  empleado) e incluso **combinaciones** que individualmente no identifican pero juntas sí.
  Para el Proyecto 2: las transcripciones son trivialmente datos personales, pero también lo
  pueden ser presupuestos que combinan sector + importe + fecha + geografía si el conjunto
  reduce la población candidata a un único cliente identificable.
- **Anonimización vs pseudonimización.**
  - **Anonimización irreversible** — ni siquiera el operador puede recuperar el dato
    original; deja de ser "dato personal" a efectos de GDPR (con condiciones).
  - **Pseudonimización** — el dato real se sustituye por uno ficticio mediante un mapping
    reversible que se conserva por separado; **sigue siendo dato personal** (la mapping table
    es información personal), pero su gestión es más sencilla. Para RAG suele ganar porque
    **preserva la coherencia semántica**: "Juan García" no se reemplaza por `<PERSON>` (que
    destruye estructura), sino por "Carlos Martínez" siempre, en todo el corpus.
- **Derecho al olvido (artículo 17).** Cualquier persona puede pedir que sus datos sean
  eliminados. En una BBDD tradicional es un `DELETE`. En RAG es un **problema
  arquitectónico**: los chunks que mencionan al individuo están vectorizados y dispersos. Sin
  un mapeo explícito que diga "estos chunks contienen información sobre Juan García", la
  eliminación es imposible. Esta es una de las razones por las que la mapping table es una
  pieza arquitectónica, no un detalle.
- **Minimización.** Solo se deben procesar los datos estrictamente necesarios para el
  propósito declarado. ¿Necesita el sistema de estimación los nombres reales de los clientes?
  La respuesta razonable es **no**: necesita los **patrones** de proyectos pasados (sector,
  alcance, tecnologías, complejidad), no la identidad concreta. Esa observación justifica la
  pseudonimización agresiva desde el principio: no perdemos nada útil, eliminamos un riesgo.

## 5.4 Microsoft Presidio: detección y anonimización en pipeline

**Presidio** es la librería de Microsoft para detección y anonimización de PII. Frente a
alternativas (spaCy puro, nltk, AWS Comprehend), tiene tres características que la hacen
práctica: arquitectura **modular** (`analyzer` + `anonymizer` intercambiables),
**recognizers preconstruidos** para PII común (email, teléfono, IBAN, IPs, tarjetas, fechas,
ubicaciones, personas, organizaciones) y soporte explícito para **custom recognizers**.

Uso básico en dos pasos: el `analyzer` detecta entidades y sus posiciones; el `anonymizer`
aplica una transformación.

```python
# Config crucial: motor NLP en español (por defecto Presidio carga inglés).
nlp_config = {"nlp_engine_name": "spacy",
              "models": [{"lang_code": "es", "model_name": "es_core_news_md"}]}
nlp_engine = NlpEngineProvider(nlp_configuration=nlp_config).create_engine()
analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["es"])
anonymizer = AnonymizerEngine()

results = analyzer.analyze(text=text, language="es")
anonymized = anonymizer.anonymize(text=text, analyzer_results=results,
    operators={"DEFAULT": OperatorConfig("replace", {"new_value": "[REDACTED]"})})
```

**Sin la configuración en español**, la tasa de falsos negativos en entidades `PERSON` y
`LOCATION` se dispara: el sistema no detecta nombres que para un hispanohablante son obvios.
La operación `replace` con `[REDACTED]` es la más simple y **la peor para RAG** (destruye la
estructura semántica); se muestra solo para ilustrar el flujo.

## 5.5 Recognizers custom para el dominio del Proyecto 2

Los recognizers default no conocen los identificadores propios del dominio. El Proyecto 2
tiene al menos dos:

- **Budget IDs** — patrón `BUDGET-YYYY-NNNN` (el invariante del schema Pandera del Artículo
  4). No son PII en sentido estricto, pero revelan **información comercial sensible** (volumen
  de proyectos cerrados, estructura de numeración interna).
- **Códigos de cliente internos** — `CLI-1042`, `CLT-INT-A047`, que mapean uno-a-uno a
  clientes reales.

```python
budget_id_pattern = Pattern(name="budget_id_canonical",
    regex=r"\bBUDGET-\d{4}-\d{4}\b", score=0.95)
budget_id_recognizer = PatternRecognizer(supported_entity="BUDGET_ID",
    patterns=[budget_id_pattern], supported_language="es")
analyzer.registry.add_recognizer(budget_id_recognizer)
```

Dos notas:

1. **`score` es un parámetro decisivo** — indica la confianza con que el recognizer afirma
   haber detectado la entidad. Cuando varios se solapan, Presidio se queda con el de mayor
   score. Buena higiene: scores altos (0.9–0.95) en patrones muy específicos, bajos
   (0.4–0.6) en genéricos.
2. **El `supported_entity` declarado** (`BUDGET_ID`, `CLIENT_CODE`) es la **etiqueta
   semántica** que se usa después en la pseudonimización para aplicar la transformación
   correcta (un budget ID se reemplaza con otro budget ID falso; un email con otro email).

Para nombres específicos que no siguen patrón regular ("Banco Sabadell", "Inditex"), una
herramienta complementaria: `RecognizerResult` cargados desde un **diccionario explícito**
mantenido como parte del proyecto.

## 5.6 Pseudonimización reversible con Faker y una mapping table

Aquí entra la **pieza arquitectónica clave**. En lugar de reemplazar las entidades con
tokens genéricos (`[PERSON]`), las reemplazamos con **valores ficticios consistentes**
generados por Faker, manteniendo en paralelo una **mapping table** que registra cada
sustitución para poder revertirla.

```python
@dataclass
class PseudonymMapping:
    original_value: str
    pseudonym: str
    entity_type: str
    first_seen_at: str
    source_name: str   # fuente del catálogo donde apareció primero

class ConsistentPseudonymizer:
    def __init__(self, mapping_store, locale: str = "es_ES"):
        self.faker = Faker(locale)
        self.store = mapping_store  # respaldado por un store encriptado
        self.generators = {
            "PERSON": self.faker.name, "EMAIL_ADDRESS": self.faker.email,
            "PHONE_NUMBER": self.faker.phone_number, "LOCATION": self.faker.city,
            "ORGANIZATION": self.faker.company,
            "BUDGET_ID": lambda: f"BUDGET-{self.faker.year()}-...",
            "CLIENT_CODE": lambda: f"CLI-{self.faker.random_number(...)}",
        }

    def get_or_create_pseudonym(self, original, entity_type, source_name) -> str:
        existing = self.store.lookup(original, entity_type)
        if existing:
            return existing.pseudonym         # mismo original → mismo pseudónimo
        pseudonym = self.generators.get(entity_type, self.faker.word)()
        self.store.save(PseudonymMapping(original, pseudonym, entity_type, ..., source_name))
        return pseudonym
```

Cuatro elementos del diseño:

1. **La consistencia es por valor original, no por chunk.** "Juan García" siempre se
   pseudonimiza a "Carlos Martínez" aunque aparezca en cientos de chunks. Sin esto, dos
   chunks del mismo cliente acabarían en regiones distantes del espacio vectorial y el
   retrieval volvería a romperse (la misma razón que la "heterogeneidad de formato" del
   Artículo 4).
2. **Los generadores son específicos por tipo de entidad.** Un nombre se reemplaza por otro
   nombre, no por un email ni una fecha. La señal semántica del tipo de campo se preserva.
3. **La mapping store es un componente separado del pipeline**, encriptado, con su propio
   control de acceso. Si tienes que demostrar a un auditor GDPR qué datos viven en tu
   sistema, la consulta es contra ese store, no contra el corpus vectorial.
4. **El `source_name` se persiste con el mapping** — permite responder "qué fuentes del
   catálogo mencionan a esta persona" sin recorrer el índice vectorial.

**Integración:** al final del pipeline de ingest, después de la validación del Artículo 4 y
**antes del chunking de la Sesión 7**. El orchestrator toma cada `Document` validado, mira
`metadata.contains_pii` (propagado desde el catálogo en el Artículo 3) y, si es `True`,
aplica la pseudonimización. El `Document` que sale tiene el mismo `content` salvo por los
tokens reemplazados; el resto del pipeline downstream no necesita saber nada de Presidio ni
Faker.

## 5.7 El derecho al olvido en RAG: un caso práctico

Cuando un cliente o empleado dice "quiero que mis datos no estén más en vuestro sistema de
IA", con esta arquitectura los pasos son cinco:

1. **Consultar la mapping store** con el nombre del solicitante para identificar todos los
   pseudónimos asociados (pueden ser varios: nombre completo, nombre y apellido, alias).
2. **Buscar en el índice vectorial** los chunks que contienen esos pseudónimos o están
   asociados a documentos con esos pseudónimos en metadatos.
3. **Eliminar esos chunks** del índice vectorial.
4. **Eliminar las entradas correspondientes de la mapping store** — el mapping deja de
   existir; si la persona reaparece, recibirá un pseudónimo nuevo sin relación con el
   anterior.
5. **Registrar la operación en un audit log** que demuestre que la petición se atendió en
   plazo y forma.

Cada paso es operativamente trivial **gracias a la mapping table**. Sin ella, los pasos 1, 2
y 4 son imposibles, y el sistema queda en incumplimiento permanente del artículo 17. **La
mapping table no es un detalle; es la pieza que sostiene el cumplimiento.**

## 5.8 Trade-offs honestos del Artículo 5

- **Anonimización irreversible vs pseudonimización reversible.** Algunos defienden la
  irreversible por simplicidad (sustituir con `<PERSON>`, sin mapping store, sin riesgo de
  filtración del mapping, ya no es "dato personal"). El problema: **los embeddings de un
  corpus con `<PERSON>` se degradan significativamente** respecto a uno con pseudónimos
  consistentes. Pruebas internas muestran caídas del **15–25% en métricas de retrieval** con
  sustitución genérica. Para sistemas en producción con compromiso de calidad, la
  pseudonimización reversible es casi siempre la respuesta correcta. La irreversible queda
  para corpus "públicos por defecto" o casos donde un contrato legal lo exige.
- **Falsos positivos de Presidio en español.** Funciona considerablemente peor en español
  que en inglés. El modelo `es_core_news_md` etiqueta nombres comunes como entidades `PERSON`
  con frecuencia molesta ("Mar", "Sol", "Cruz", "Alba"). Tres mitigaciones: subir el umbral
  de score (0.5 → 0.7 reduce falsos positivos a costa de algunos falsos negativos), añadir
  una **blacklist** de palabras que no deben tratarse como PII, y entrenar un modelo NER
  customizado si el volumen lo justifica. Para el Proyecto 2, las dos primeras bastan.
- **Impacto en la calidad de los embeddings.** Aunque la pseudonimización consistente
  preserva la mayor parte de la señal, introduce algo de ruido inevitable: un nombre real
  lleva micro-información que un nombre falso no replica (origen geográfico, género
  percibido, frecuencia en el corpus). Para un RAG de estimación es despreciable (el
  retrieval funciona en términos de patrones de proyecto, no de identidad nominal). Para
  sistemas donde la identidad importa (asistentes personales, CRM individualizado), el coste
  es mayor. Regla del Proyecto 2: **pseudonimizar primero, medir después** con queries
  representativas, decidir caso por caso si algún tipo de entidad (rara vez) merece dejarse
  sin tratar.

---

## Cómo conecta con nuestro ejercicio y con el directo

Esta sesión es **el cimiento del Módulo 3** y, con él, de todo el bloque RAG del Proyecto 2
(el estimador). El corpus pasó por **seis decisiones acumulativas**:

1. **Artículo 1** — Justificada arquitectónicamente la transición de CAG a RAG (con capa
   híbrida residual de CAG para el contexto estable: glosarios, plantillas, tarifas).
2. **Artículo 2** — Construido el catálogo versionado de fuentes (`data_catalog.yaml`) con
   políticas explícitas de inclusión/exclusión y reporte de auditoría.
3. **Artículo 3** — Montado el subsistema `ingest/` (loaders → parsers → normalizers) con el
   `Document` canónico como contrato compartido.
4. **Artículo 4** — Implementada la capa de limpieza (pandas) y validación (Pandera) como
   guardián de los invariantes de negocio, con la política reparar/cuarentena/descartar.
5. **Artículo 5** — Cerrada la anonimización mediante Presidio + mapping table que sostiene
   el cumplimiento GDPR.

Lo que tenemos al final del módulo no es código brillante; es **un corpus que un equipo de
producción podría defender ante cualquier interlocutor** (legal, comercial, técnico,
regulatorio). Cada decisión está versionada, cada exclusión tiene motivo registrado, cada
dato sensible tiene mapping reversible, cada invariante de negocio tiene un schema que lo
hace cumplir.

**Hacia delante:** en la **Sesión 7** se ataca la vectorización propiamente dicha
(embeddings, chunking, modelos, espacio vectorial). En la **Sesión 8**, las bases de datos
vectoriales y pgvector. El trabajo de esta sesión va a seguir siendo el cimiento sobre el
que se monta todo lo que viene, y la calidad de ese cimiento determina cuánto vale el
sistema final en producción.

> **Divergencias de nuestra implementación** (ver memorias de proyecto): la sesión oficial
> asume Drive/Dropbox/S3 como fuentes y un stack genérico; nuestro estimador porta el
> pipeline a single-Postgres con `psycopg` v3 (no psycopg2) y `DbSessionStore`. La capa de
> ingesta, limpieza Pandera y anonimización Presidio se adaptan a esas divergencias, no se
> copian literalmente.

---

### Chuleta de una página (lo imprescindible)

- **Por qué RAG, no CAG.** El techo del CAG son 4 restricciones simultáneas: context
  window, coste/consulta, latencia y **degradación de atención** (*lost in the middle*).
  Basta que una falle. La calidad del dato es la **variable de control**: RAG recupera y
  presenta; basura entra, basura sale.
- **Dos pipelines, no uno.** Offline (ingest→parse→chunk→embed): background, minutos-horas,
  modelos pesados. Online (retrieve→augment→generate): síncrono, <3s, quirúrgico. **No
  mezclarlos.**
- **Árbol de decisión (4 ejes).** Trazabilidad o control de acceso por usuario → RAG. No
  cabe (>70% del contexto) → RAG. Cambia <7 días → RAG. Estable (>90 días) y pequeño
  (<30%) → CAG. Resto → **híbrido**. Fine-tuning ≠ alternativa: es capa encima.
- **Audita antes de vectorizar.** Censo (nombre lógico, owner, formato, volumen,
  periodicidad **declarada vs observada**). Calidad en 4 dimensiones (completitud,
  consistencia, actualidad, fiabilidad) **sin promediar**: cada una es condición necesaria.
  Linaje contra la **context erosion**.
- **El catálogo es código.** `data_catalog.yaml` versionado + loader Pydantic. Decisión
  `include/exclude/review` por fuente. Excluir fuentes malas es **disciplina**, no desidia.
- **Un `Document` canónico** (`content` + `metadata`) como contrato. Arquitectura
  `ingest/`: **loaders** (acceso) → **parsers** (formato, representación intermedia) →
  **normalizers** (a Document). Tres capas por testabilidad.
- **Parsing por formato.** JSON → markdown estructurado (no `json.dumps`). TXT → turnos con
  speaker. XLSX → tabla markdown si es tabla pura. DOCX → un Document por sección/heading.
  PDF → `pypdf` por defecto, `unstructured hi_res` solo si tablas/escaneo.
- **Limpieza ≠ validación.** Cuatro suciedades: heterogeneidad, duplicados con divergencia,
  nulos disfrazados, valores fuera de rango. Capa **entre parser y normalizer**. pandas
  normaliza (coerciones permisivas → `NaN`); **Pandera** valida (`strict=True`,
  cross-column checks, `lazy=True`). Política: **reparar / cuarentena / descartar**.
- **PII antes del embedding.** El control de acceso **no** protege en RAG (filtración
  semántica indirecta: directa / agregación / inferencia). GDPR: datos personales (amplio),
  anon vs **pseudo** (gana pseudo por coherencia semántica), derecho al olvido (art. 17),
  minimización.
- **Presidio + Faker + mapping table.** Config NLP en español (`es_core_news_md`). Custom
  recognizers (`BUDGET_ID`, `CLIENT_CODE`) con `score`. **Pseudonimización consistente por
  valor original** (mismo nombre → mismo pseudónimo). La **mapping table encriptada** es la
  pieza que hace posible el derecho al olvido. Sustitución genérica `<PERSON>` cuesta
  **15–25%** de retrieval.
