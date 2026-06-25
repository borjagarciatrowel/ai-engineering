# Sesión 06 — Calidad del dato, ingesta y pipeline para RAG (versión clara)

> Versión simplificada del doc original de la Sesión 6 (Módulo 3). Misma información, menos paja.
> Cada término técnico se explica en una frase, justo donde aparece.
> **Hilo conductor:** un sistema (Proyecto 2) que recibe transcripciones de reuniones de cliente y genera estimaciones de proyectos software usando histórico de presupuestos.

Esta sesión cubre todo lo que pasa **antes** de vectorizar un solo documento: por qué se elige RAG, cómo auditar las fuentes, cómo extraer el contenido, cómo limpiarlo/validarlo y cómo proteger los datos sensibles. La vectorización (embeddings, chunking) empieza en la Sesión 7; las bases vectoriales, en la Sesión 8.

---

## Glosario base (léelo una vez y vuelve cuando haga falta)

| Término | Qué es, en una frase |
|---|---|
| **RAG** (*Retrieval-Augmented Generation*) | El sistema **recupera** fragmentos relevantes de un corpus y se los pasa al modelo para que responda con ellos. |
| **CAG** (*Context-Augmented Generation*) | Meterle al modelo **todo** el contexto de golpe en cada llamada. Simple, pero no escala. |
| **Corpus** | El conjunto de documentos sobre el que trabaja el sistema. |
| **Context window** | Capacidad máxima de tokens que el modelo acepta por llamada. |
| **Token** | Unidad mínima de texto que procesa el modelo (≈ un trozo de palabra). |
| **Embedding / vector** | Convertir un texto en una lista de números que captura su significado; textos parecidos → vectores cercanos. |
| **Chunk** | Un trozo de documento (párrafo, sección). No se indexan documentos enteros, sino chunks. |
| **Metadatos** | Datos *sobre* el documento que no están en su texto: origen, fecha, autor, página, sensibilidad. |
| **Trazabilidad** | Poder citar de qué fuente concreta sale cada afirmación. |
| **PII** (*Personally Identifiable Information*) | Datos que identifican a una persona: nombres, emails, teléfonos, IDs internos. |
| **Pipeline** | La cadena de pasos por los que pasa un dato (o una consulta). |
| **Pydantic** | Librería Python que valida que un objeto cumple un esquema (tipos, campos obligatorios). |

> La frase que conviene interiorizar:
> *"No amount of clever chunking or fancy architecture can fix fundamentally bad data."*
> (Ninguna estrategia de troceado ni arquitectura sofisticada arregla datos malos de raíz.)

---

## La idea en una página

Un RAG **no inventa**: recupera y presenta. Si recupera basura, presenta basura bien formateada — y suena igual de segura que una respuesta buena. Por eso, antes de tocar embeddings, dedicamos tres sesiones a los datos. El recorrido de esta sesión son cinco eslabones:

| # | Pregunta | Qué resuelve | Artículo |
|---|----------|--------------|----------|
| 1 | **¿Por qué RAG y no otra cosa?** | Marco de decisión para defender la arquitectura ante cualquier stakeholder | 1 |
| 2 | **¿Qué tengo y en qué estado está?** | Auditoría e inventario de fuentes antes de procesar nada | 2 |
| 3 | **¿Cómo convierto cada formato en texto?** | Pipeline de extracción multi-formato con un contrato común | 3 |
| 4 | **¿Cómo garantizo que el contenido es correcto?** | Limpieza, normalización y validación | 4 |
| 5 | **¿Cómo protejo los datos personales?** | Anonimización y GDPR | 5 |

> Al final no tendremos código brillante, sino algo más valioso: **un corpus que un equipo de producción podría defender ante un interlocutor legal, comercial, técnico o regulatorio.** Ese es el estado mínimo desde el que tiene sentido vectorizar.

---

# PARTE 1 — Calidad del dato y la decisión CAG vs RAG

## 1.1 El verdadero techo del CAG (no es solo el context window)

El error junior es creer que el CAG solo se rompe porque "no cabe en el contexto". Es engañoso. El CAG tiene un techo de **cuatro restricciones que operan a la vez**:

| Restricción | Qué es | Tipo |
|---|---|---|
| **Context window** | El corpus supera el máximo de tokens y no se puede inyectar entero. | Binaria, obvia |
| **Coste por consulta** | El coste sube linealmente con los tokens de entrada. 3 céntimos/consulta es desplegable; 2 €, casi nunca. | Continua — suele matar el proyecto la primera |
| **Latencia** | Procesar 100K tokens lleva varios segundos. Inviable para un asistente síncrono; irrelevante para un batch nocturno. | Depende del producto |
| **Degradación de atención** | La más subestimada. Los modelos **no procesan 200K tokens con la misma fidelidad que 5K**. | Aunque quepa, baja la calidad |

> **Lost in the middle** = fenómeno por el que la información en la mitad del contexto se recupera peor que la de los extremos.

```python
from dataclasses import dataclass

@dataclass
class CAGViability:
    fits_in_context_window: bool      # ¿Cabe técnicamente?
    cost_per_query_acceptable: bool   # ¿Es viable económicamente?
    latency_acceptable: bool          # ¿Responde dentro del SLA?
    quality_holds_with_load: bool     # ¿La calidad se mantiene con carga?

    def is_viable(self) -> bool:
        return all([self.fits_in_context_window, self.cost_per_query_acceptable,
                    self.latency_acceptable, self.quality_holds_with_load])
```

> **Conclusión empírica:** basta con que una falle para que el CAG no sea viable. Y casi nunca falla solo una.

## 1.2 Por qué la calidad del dato es la variable de control

Un RAG recupera y presenta; no genera información. Por tanto:

- Recupera ruido → presenta ruido bien formateado.
- Recupera datos desactualizados → presenta desinformación con apariencia de respuesta autorizada.
- Datos duplicados/inconsistentes → **ningún reranker ni cross-encoder lo arregla en consulta.**

> **Reranker / cross-encoder** = componente que reordena resultados en tiempo de consulta (Sesión 10). Aquí lo importante: no salva datos malos de origen.

Lo traicionero: el sistema **parece funcionar bien al principio** (corpus pequeño, queries de prueba elegidas por el equipo). La degradación aparece cuando el corpus crece, llegan preguntas no anticipadas y los datos se vuelven incongruentes (dos versiones contradictorias del mismo presupuesto en el índice). Para entonces el pipeline ya está construido sobre supuestos falsos.

## 1.3 El pipeline RAG como abstracción de seis pasos

Descomposición canónica (popularizada por Databricks):

1. **Ingest** — recoger datos de las fuentes (BBDD, ficheros, APIs).
2. **Parse** — extraer texto y metadatos limpios de cada formato.
3. **Chunk** — trocear los documentos.
4. **Embed** — convertir cada fragmento en un vector.
5. **Retrieve** — recuperar los fragmentos más relevantes para una consulta.
6. **Generate** — pasar al LLM la consulta + los fragmentos recuperados.

## 1.4 Offline vs online: la línea que cambia toda la arquitectura

La trampa de esa lista es parecer un flujo lineal en tiempo real. No lo es: los seis pasos se reparten en **dos pipelines distintos**.

| | **Offline (indexación)** | **Online (consulta)** |
|---|---|---|
| Pasos | 1–4: ingest → parse → chunk → embed | 5–6: retrieve → augment → generate |
| Ejecución | Background, sin usuario esperando | Síncrono, usuario esperando |
| Presupuesto de tiempo | Minutos a horas | < 3 segundos (típico) |
| Disparado por | Eventos (subida de doc, cron nocturno) | Preguntas del usuario |
| Acceso a | Datos crudos | Solo vectores y metadatos indexados |

Consecuencias:
- El **offline puede usar modelos pesados** (OCR, embeddings grandes, validadores estrictos): la latencia no importa.
- El **online tiene que ser quirúrgico**: búsqueda vectorial rápida, construcción del prompt, llamada al LLM.
- Para el backend de negocio: la indexación se invoca **asíncrona** (dispara y olvida); la query, **síncrona y bloqueante**.

> Mezclar responsabilidades es uno de los antipatrones más comunes. Si la distinción no está clara desde el día 1, acabas con un servicio que se cuelga porque intenta indexar 200 PDFs mientras procesa una consulta. En la práctica: **dos endpoints disjuntos** (`POST /index/run` asíncrono, `POST /query` síncrono).

## 1.5 El árbol de decisión: CAG, RAG, fine-tuning e híbrido

La decisión se articula sobre **cuatro ejes**: (1) volumen del corpus relativo al context window, (2) frecuencia de actualización, (3) requisito de trazabilidad, (4) sensibilidad de los datos (PII, control de acceso por usuario).

```python
class Architecture(Enum):
    PURE_CAG = "pure_cag"
    HYBRID_CAG_RAG = "hybrid_cag_rag"
    PURE_RAG = "pure_rag"

def recommend_architecture(corpus: CorpusProfile, model: ModelProfile) -> Architecture:
    context_usage = corpus.total_tokens / model.context_window
    if corpus.requires_source_attribution:        # trazabilidad → RAG
        return Architecture.PURE_RAG
    if corpus.requires_per_user_access_control:   # acceso por usuario → RAG
        return Architecture.PURE_RAG
    if context_usage > 0.7:                        # no cabe con margen → RAG
        return Architecture.PURE_RAG
    if corpus.update_frequency_days < 7:           # cambia muy a menudo → RAG
        return Architecture.PURE_RAG
    if corpus.update_frequency_days > 90 and context_usage < 0.3:  # estable y pequeño → CAG
        return Architecture.PURE_CAG
    return Architecture.HYBRID_CAG_RAG             # resto → híbrido
```

> **Fine-tuning** = reentrenar el modelo con datos propios. **No es alternativa a RAG**: es una capa que se suma encima (de RAG o CAG) cuando hay límites que no resuelve un mejor retrieval (estilo de respuesta propio, terminología, formato estructurado). Regla de oro: si el modelo base sobre fragmentos bien recuperados ya responde bien, no hace falta. **Lo que nunca funciona es usar fine-tuning como sustituto de un retrieval mal diseñado.**

## 1.6 El caso del Proyecto 2 sobre el árbol

| Eje | Valor en el Proyecto 2 | Empuje |
|---|---|---|
| **Volumen** | Crece linealmente; cientos de docs/año | → RAG |
| **Frecuencia** | Alta: reuniones semanales, presupuestos mensuales | → RAG |
| **Trazabilidad** | Crítica: una estimación de 80.000 € necesita precedentes que la justifiquen | → RAG |
| **Sensibilidad** | Alta: info comercial, nombres de cliente, condiciones contractuales | → RAG |

Tres de los cuatro ejes empujan a RAG. **Matiz:** partes del contexto sí son pequeñas y estables (glosario de tecnologías, plantillas de presupuesto, tarifas oficiales). Para esas, el CAG tradicional sigue siendo mejor (más simple, barato y predecible que vectorizarlas). Por eso el sistema final será **híbrido**: CAG conviviendo con RAG, **no una sustituyendo a la otra**.

## 1.7 Trade-offs honestos del Artículo 1

- **El coste oculto de la trazabilidad.** Citar fuentes exige preservar metadatos en cada chunk (origen, página, fecha, autor), propagarlos por todo el pipeline, devolverlos al backend y construir UI que los muestre. Si tu producto puede no citar, el sistema se simplifica mucho.
- **El coste real de operar RAG.** Las comparativas CAG vs RAG suelen ser tramposas: RAG añade el coste de embeddings (uno por chunk), de la BBDD vectorial, del pipeline de indexación y de las re-indexaciones. **RAG puede ser más caro que CAG** en corpus que caben en el context window. La elección no se hace por coste, sino por **viabilidad y funcionalidad**.
- **El CAG no muere, cambia de papel.** El sistema final es **"RAG además de CAG"**: coexisten el contexto estático (instrucciones, esquemas, glosarios) y el recuperado dinámicamente (RAG).

---

# PARTE 2 — Auditoría e inventario de datos empresariales

## 2.1 El antipatrón: vectorizar primero, mirar después

El reflejo senior es ponerse a programar. En RAG tiene un **coste asimétrico**: los errores de saltarse la auditoría no aparecen el día 1, sino el día 60, con el pipeline ya montado sobre supuestos no verificados. Tres **modos de fallo**:

1. **Mezcla silenciosa de versiones.** Dos versiones contradictorias del mismo presupuesto (propuesta inicial vs firmada) y el RAG recupera la equivocada porque ningún metadato las distingue.
2. **Fuentes podridas.** Documentos que parecen válidos pero contienen info obsoleta (políticas/tarifas que cambiaron) → respuestas seguras y falsas.
3. **Gaps invisibles.** El sistema responde bien donde hay datos y **genera información plausible y falsa donde no los hay**, porque nadie supo decir que esa categoría no está cubierta.

> Misma raíz: nadie miró lo que había antes de procesarlo. **La auditoría no es un trámite previo al trabajo real; es el trabajo real.**

## 2.2 Inventario de fuentes: el censo de lo que tienes

Primer paso operativo: un **censo** factual y verificable. Campos mínimos por fuente:

- **Nombre lógico** — identificador estable (`historical_budgets`, no "los presupuestos viejos del Drive").
- **Localización física** — path o URL exacto, con el sistema de almacenamiento.
- **Owner técnico** — responsable de que exista y sea accesible.
- **Owner de negocio** — responsable del contenido (a quién preguntas cuando es ambiguo).
- **Formato físico** — JSON, CSV, PDF, DOCX, TXT, fila de BBDD, respuesta de API.
- **Volumen actual** — nº de registros y tamaño en disco.
- **Método de acceso** — FTP, API, descarga manual, query SQL.
- **Periodicidad declarada** — cada cuánto cambia *oficialmente*.
- **Periodicidad observada** — cada cuánto cambia *realmente*.

> La pareja **declarada vs observada** revela problemas que nadie había mirado: una fuente que oficialmente es mensual pero cuya última modificación es de hace 7 meses **no es mensual; es una fuente abandonada que alguien cree viva.**

El censo no se hace de cabeza: se ejecuta un script de inspección (p.ej. una dataclass `FilesystemSourceFacts` con `name`, `path`, `file_count`, `total_size_mb`, `latest_modified`, `formats_detected`) y se completan a mano los campos subjetivos.

## 2.3 Evaluación de calidad por dimensiones

"Datos abundantes" ≠ "datos buenos". Cuatro dimensiones (escala 1–5):

- **Completitud.** ¿Cuántos registros tienen todos los campos? ¿Cuántos tienen `total_amount` como string o vacío?
- **Consistencia.** ¿El mismo concepto se representa igual? `currency` = `EUR` o variantes (`euros`, `€`, `eur`). Las inconsistencias son veneno para chunking y retrieval.
- **Actualidad.** ¿Qué fecha tiene el último dato relevante? `last_modified` de hace dos años → probablemente no es una fuente viva.
- **Fiabilidad.** ¿Autoritativa o derivada? Una hoja rellenada a mano trimestralmente es menos fiable que el output de un sistema transaccional validado.

```python
class QualityScore(IntEnum):
    UNUSABLE = 1; POOR = 2; ACCEPTABLE = 3; GOOD = 4; EXCELLENT = 5

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
        return all(score >= QualityScore.ACCEPTABLE
                   for score in (self.completeness, self.consistency,
                                 self.actuality, self.reliability))
```

> **El promedio engaña.** Una fuente con `completeness=5` y `reliability=1` no es "calidad 3": está completa pero puede ser mentira, lo peor para RAG. Las dimensiones **no se compensan**; cada una es condición necesaria.

## 2.4 Linaje y context erosion

> **Linaje** (*lineage*) = el rastro del origen y las transformaciones de un dato. En BI es buena práctica; en RAG es **condición de utilidad** (el usuario necesita verificar de qué documento viene un fragmento, cuándo se generó y qué autoridad tiene).

> **Context erosion** (erosión de contexto) = la pérdida progresiva de contexto a medida que el dato se mueve entre sistemas.

```
ERP record BUDGET-2024-0315   (todos los metadatos intactos)
  → presupuesto_v3.pdf        (exportado a Drive, solo metadatos de subida)
  → cliente_acme_2024.pdf     (descargado y renombrado, solo nombre + fecha)
  → cliente_acme.txt          (extracción de texto, sin metadatos)
```

La información sigue ahí, pero **el contexto que la hacía interpretable se ha evaporado.** Combatir la context erosion es la razón de ser del **catálogo**: el sitio donde se preserva, versionado y por construcción, el contexto que se perdería si confías solo en los nombres de fichero.

## 2.5 El catálogo mínimo viable como YAML versionado

Toda la info recolectada (censo, calidad, decisiones, linaje) vive en el repositorio como un **YAML versionado** (`data_catalog.yaml`):

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

> El catálogo **es un artefacto de software, no documentación muerta.** Cualquier código que toque las fuentes lo lee al arrancar para saber qué procesar, qué excluir y qué metadatos propagar.

Necesita un **loader tipado** (modelos Pydantic: `IngestionDecision`, `Volume`, `Refresh`, `Quality`, `Sensitivity`, `Lineage`, `CatalogSource`, `DataCatalog` con `included_sources()` y `load_catalog()`). Tres ventajas de tenerlo como código:

1. **Validación automática** — un PR que rompe el schema no llega a producción.
2. **Acoplamiento explícito** — el pipeline itera sobre `catalog.included_sources()` y propaga `lineage.upstream` y `sensitivity` como metadatos de cada chunk.
3. **Trazabilidad de cambios** — el `git log` del YAML es el historial de cómo evoluciona el corpus y por qué se incluyó/excluyó cada fuente.

## 2.6 El reporte de auditoría como deliverable

Pieza opcional pero recomendable: un **reporte de auditoría** generado automáticamente (`generate_audit_report(catalog) -> str`, en Markdown) para comunicar el estado del corpus a quien no lee YAML (producto, comité, cliente). Generarlo en cada cambio (en CI) lo mantiene vivo.

> **El catálogo no se escribe al principio y se olvida; es un artefacto que respira con el proyecto.**

## 2.7 Trade-offs honestos del Artículo 2

- **Catálogo formal vs YAML en repo.** Existen plataformas profesionales (Atlan, DataHub, Collibra, Microsoft Purview) con descubrimiento automático, linaje a nivel de columna y governance. Tienen sentido con cientos de fuentes y un equipo dedicado. Para una o dos docenas de fuentes, el YAML versionado es lo correcto **hasta** que el número crece o aparece un mandato regulatorio. Migrar de YAML a plataforma es trivial; saltar directo a la plataforma suele dar una herramienta cara y vacía.
- **Auditoría exhaustiva vs suficiente para arrancar.** Las fuentes son móviles: lo que documentes hoy estará desfasado en dos meses. La auditoría inicial cubre solo las fuentes del **primer release**, no todas las de la organización. El catálogo crece con el proyecto, no antes que él.
- **Decidir qué dejar fuera deliberadamente.** Falacia común: "toda fuente disponible debe usarse". En RAG es peligrosa porque las fuentes malas no se manifiestan como ruido aleatorio (fácil de detectar) sino como **respuestas seguras a información incorrecta**. El `rate_card_2024.xlsx` desactualizado es el caso típico: oficialmente es la fuente de la verdad, pero incluirlo introduciría errores sistemáticos. **Excluir fuentes dejando registrado por qué es disciplina arquitectónica, no desidia.**

---

# PARTE 3 — Pipeline de extracción multi-formato

Con el catálogo cerrado, toca convertir el contenido físico de cada fuente en texto procesable. El Proyecto 2 tiene **cinco familias de formato**: JSON (presupuestos), TXT (transcripciones), XLSX (tarifarios), DOCX (plantillas), PDF (contratos y propuestas). Cada una con su maldición.

> La tentación es instalar `unstructured`, llamar a `partition()` y darlo por resuelto. Es correcto a corto plazo e incorrecto a medio: delegar todo a una librería sin pensar la arquitectura es como se construyen los pipelines que dos meses después nadie entiende. El patrón opuesto: **arquitectura modular donde cada formato usa la herramienta correcta y todo confluye en un contrato común.**

## 3.1 El contrato común: el `Document` canónico

> **Document canónico** = objeto único que produce el subsistema `ingest/` para el resto del servicio. Tiene dos campos esenciales: **contenido textual** y **metadatos**. (En la literatura: `Document`, `Chunk` o `Passage`.)

```python
class DocumentMetadata(BaseModel):
    """Metadatos que viajan con cada documento por el pipeline."""
    source_name: str         # coincide con una entrada de data_catalog.yaml
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

Dos virtudes: **homogeneidad downstream** (el módulo de chunking no necesita saber si el `Document` viene de un PDF escaneado o de un JSON; procesa `content` y propaga `metadata`) y **trazabilidad por construcción** (cada documento sabe de qué fuente viene y, cuando el formato lo permite, en qué página/sección). El campo `extra` es una válvula de escape consciente.

## 3.2 Arquitectura modular del subsistema `ingest/`

Tres capas que separan responsabilidades por tipo de problema:

```
servicio_ia/
└── ingest/
    ├── loaders/        # acceso físico a fuentes (filesystem, drive, http)
    ├── parsers/        # extracción por formato (json, pdf, docx, xlsx, txt)
    ├── normalizers/    # homogeneización a Document (canonical.py)
    ├── catalog.py      # loader del data_catalog.yaml (Artículo 2)
    └── orchestrator.py # pega todo y produce Document[]
```

| Capa | Responsabilidad | Detalle |
|---|---|---|
| **Loaders** | "Cómo llego al fichero" | Saben de paths, URLs HTTP, auth de Drive, claves de S3. Entregan bytes/stream; no saben qué hay dentro. (Un PDF puede vivir en Drive, S3 o disco; no triplicamos su parser por ubicación.) |
| **Parsers** | "Qué hay dentro" | Reciben bytes, eligen librería por formato, producen una **representación intermedia** específica (DataFrame para Excel, lista de elementos para PDF). **No es el `Document` todavía.** |
| **Normalizers** | "Cómo paso mi parser al contrato canónico" | Capa fina: representación intermedia → `Document`, propagando metadatos del catálogo. |

> ¿Por qué tres capas y no dos? **Testabilidad.** Separar la normalización permite testear parsers contra su representación intermedia (fácil de mockear) y normalizers contra el contrato canónico, sin rellenar metadatos del catálogo en cada test.

## 3.3 Estrategias de parsing por formato

| Formato | Maldición | Estrategia |
|---|---|---|
| **JSON** | Parece fácil porque ya tiene estructura | No extraer texto: decidir qué representación entra al RAG. `json.dumps()` genera embeddings ruidosos (mezcla claves técnicas con valores semánticos). **Mejor: renderizar a markdown estructurado** (claves importantes → títulos, valores → prosa). |
| **TXT** | Las transcripciones no son texto homogéneo | Las nuevas: `[hh:mm:ss] Speaker: ...`; las viejas, heterogéneas. Tratarlas como bolsa de texto pierde **quién dijo qué**. Parser que detecta el formato y produce turnos con metadatos `speaker` y `timestamp`. |
| **XLSX** | El más traicionero: parece tabular y rara vez lo es | Celdas combinadas, fórmulas, múltiples tablas/hoja, hojas ocultas. Extraer la tabla principal con `openpyxl`/`pandas.read_excel()` a markdown. **Regla: tabla pura → tabla markdown; estructura compleja → no debería estar en el corpus o requiere conversión manual.** |
| **DOCX** | Sorprendentemente amable | `python-docx` recorre párrafos, tablas y headings con API limpia. Extraer **secciones por heading** (`Alcance`, `Entregables`, `Cronograma`) → un `Document` por sección con el heading como `section_title`. |
| **PDF** | El infierno: es formato de presentación, no de contenido | Estructura semántica implícita (posiciones, fuentes, tamaños). Tres opciones ↓ |

Opciones para PDF:

1. **`pypdf` / `pdfplumber`** — texto plano: rápido y barato, pierde tablas, columnas y estructura.
2. **`pymupdf` (alias `fitz`)** — mejor layout, imágenes y bounding boxes. Buena opción para PDF de texto digital limpio.
3. **`unstructured` con `strategy="hi_res"`** — visión por ordenador para detectar tablas, encabezados y secciones. Correcta con tablas relevantes o escaneos que requieren OCR. **La más lenta y cara con diferencia.**

> Regla del Proyecto 2: `pypdf` por defecto; `unstructured`+`hi_res` solo cuando se detecta que el PDF tiene tablas o es escaneado. **La decisión se toma una vez por fuente en el catálogo, no por documento.**

## 3.4 El parser universal con `unstructured` como navaja suiza

> **`unstructured`** = librería cuyo `partition()` detecta el formato y devuelve una lista de `Element` heterogéneos (`Title`, `NarrativeText`, `Table`, `ListItem`) con metadatos de localización.

- **Ventajas reales:** unifica el interface, soporta 20+ formatos, detección de estructura sorprendentemente buena.
- **Costes:**
  - **Peso** — `unstructured[all-docs]` mete cientos de MB en la imagen Docker (Tesseract, modelos de detección, PyTorch).
  - **Latencia/coste** — `hi_res` es un orden de magnitud más lento que un parser nativo para PDFs simples.
  - **Opacidad** — cuando algo falla, depurar es difícil: buena parte del trabajo lo hace un modelo neuronal que no explica sus decisiones.

> Recomendación: **parsers nativos para formatos predecibles** (JSON, TXT, XLSX simple, DOCX); **`unstructured` reservado para PDF cuando lo necesita** (tablas, escaneo) y como fallback para formatos exóticos.

## 3.5 Propagación de metadatos a través del pipeline

Los metadatos que viajan con cada documento permiten al RAG citar. Su fuente es **triple**:

- **Del catálogo** — conocidos antes de tocar el documento (nombre lógico, owner, sensibilidad PII, decisión). Uniformes para toda la fuente.
- **Del parser** — conocidos tras procesar (título de heading, autor, fecha, número de página, sección).
- **Del pipeline** — conocidos en el momento del procesamiento (`ingested_at`, versión del parser, config). Útiles para depuración y reproducibilidad.

El **orchestrator** combina las tres fuentes:

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

1. `Parser` como **Protocol** (structural typing) en vez de clase abstracta: más flexible y testeable.
2. El orchestrator **respeta la decisión del catálogo**: `exclude`/`review` no se procesan.
3. Los metadatos del catálogo se aplican **después** del parser: si un parser intentara falsificar `source_name`, el orchestrator lo sobrescribe con el valor canónico.

## 3.6 Trade-offs honestos del Artículo 3

- **Parsers nativos vs `unstructured` universal.** No es tribu, es contexto: <5-6 formatos predecibles → nativos (rápidos, baratos, fáciles de depurar); docenas de formatos heterogéneos → `unstructured` (evita reinventar veinte ruedas).
- **`hi_res` vs `fast` en PDF.** Usar `hi_res` para todo "por seguridad" puede costar 20× más sobre 100 PDFs, sin aportar nada en los 90 que son texto digital limpio. Clasificar los PDFs en el catálogo (digital limpio, digital con tablas, escaneado) es trabajo manual de una vez; el ahorro es continuo.
- **Pérdida de información estructural aceptable.** Hay info que no sobrevive (imágenes embebidas en DOCX, comentarios de Word, anotaciones en márgenes de PDF, formato condicional de Excel). Para un RAG de estimación es ruido prescindible; para un RAG de revisión legal de contratos, las anotaciones serían críticas. **Lo inaceptable es perder información por descuido en lugar de por diseño.**

---

# PARTE 4 — Limpieza, normalización y validación de datos

Los `Document` que produce `ingest/` cumplen el contrato Pydantic (`content` no vacío, `metadata` con campos requeridos). Pero eso es solo el **contrato de forma**, no el **de contenido**. Dos `Document` pueden cumplir Pydantic y ser incompatibles para RAG:

- `client_name: "ACME Corp."` y `"Acme Corp"` → válidos, pero los embeddings los tratan como entidades distintas y el retrieval falla en silencio.
- `total_amount: -50000` → pasa el tipo (es número) y rompe cualquier aritmética.
- `"15/03/2024"` y `"2024-03-15"` → ambas strings válidas, radicalmente diferentes para filtrar por tiempo.

> Pydantic es la **primera línea de defensa, no la última.** Este artículo monta la segunda: la capa de limpieza y validación que garantiza el **contrato de contenido** antes del embedding.

## 4.1 Cuatro familias de "suciedad" en datos para RAG

1. **Heterogeneidad de formato.** La misma cosa escrita de N maneras: fechas (`15/03/2024`, `2024-03-15`, `March 15 2024`), monedas (`EUR`, `eur`, `€`, `euros`), identificadores (`ACME`, `Acme Corp.`, `acme-corp`). Veneno: los embeddings tratan cada variante como un token distinto → dos fragmentos del mismo cliente acaban lejos en el espacio vectorial.
2. **Duplicados con divergencias.** El mismo registro existe dos veces con valores distintos (`total: 80000` en el JSON del ERP, `82500` en la copia manual). El RAG recupera el que se indexó primero. Diagnosticarlo en producción lleva semanas porque el sistema no se rompe: da respuestas inconsistentes que "parecen ruido del LLM".
3. **Valores nulos disfrazados.** Campos que parecen rellenados pero no informan: `"N/A"`, `"-"`, `"unknown"`, `"TBD"`, `"pendiente"`, cadena vacía, un espacio. Pasan la validación de tipo, se vectorizan como contenido real, y el RAG aprende a "recuperar" estos valores como si significaran algo.
4. **Valores fuera de rango.** `total: -50000`, fechas de fin anteriores al inicio, porcentajes >100, `hours_estimated` en millones. Impacto asimétrico: rara vez se recuperan (los embeddings los aíslan), pero cuando lo hacen generan **respuestas con confianza alta sobre afirmaciones absurdas** — las que más caro pagan los stakeholders en credibilidad.

> Todas requieren la misma decisión: **un punto único del pipeline donde se aplican las reglas, con un contrato explícito de qué pasa y qué no.**

## 4.2 Dónde colocar la capa de limpieza

La tentación es resolver cada problema donde se descubre (el chunker detecta un campo vacío, el embedder un duplicado...). **Es justo lo que no hay que hacer:** las reglas dejan de ser auditables, los tests se vuelven imposibles (testear el chunker exige mockear validaciones de otra capa) y el sistema queda sin un único punto donde un fallo pueda detenerlo.

> La capa de limpieza es un **módulo separado**, y su posición natural es **entre el parser y el normalizer** (`loaders → parsers → [LIMPIEZA] → normalizers → Document`).

Para formatos tabulares (JSON de presupuestos), la representación intermedia es un `DataFrame` de pandas. Los no tabulares (PDF, DOCX, TXT) tampoco escapan: sobre sus representaciones (listas de elementos, texto) se aplican otras técnicas (regex, validación de encoding, longitud mínima, detección de placeholders).

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
    # 5. Dedup: quedarse con la última versión por budget_id
    out = out.sort_values("signed_at").drop_duplicates(subset=["budget_id"], keep="last")
    return out
```

Tres detalles:

1. **Cada paso hace una cosa** — facilita testear en aislamiento.
2. **El paso 5 (dedup)** ataca los "duplicados con divergencias". La regla "quédate con el último según `signed_at`" debe ser **decisión consciente del equipo, documentada en el catálogo**.
3. **Coerciones permisivas** (`errors="coerce"`) convierten valores inválidos en `NaN` en vez de lanzar excepción. Esto separa limpieza de validación: aquí transformamos lo transformable; la validación posterior decide qué hacer con los `NaN`.

> Esta función **no decide nada**: deja registros con campos vacíos, valores fuera de rango y fechas no parseables (`NaT`). Qué pasa con ellos lo decide la capa de validación.

## 4.4 Pandera como contrato de datos

> **Pandera** = lo que Pydantic es a una instancia, pero para DataFrames: "este DataFrame cumple este schema columna a columna y fila a fila, o produce un reporte de qué filas fallan y por qué".

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

Tres elementos:

1. **Checks de campo** (`ge=0`, `le=10_000_000`, `str_matches`) — cada uno es un **invariante de negocio**. La forma del `budget_id` no es estética; es un contrato con el sistema upstream.
2. **Checks cross-column** (`@pa.dataframe_check`) — relacionan varias columnas ("si `signed`, el total no puede ser cero"). Detectan inconsistencias sutiles que un schema solo-Pydantic no puede expresar.
3. **Configuración** — `strict=True` rechaza columnas no declaradas (defensa contra cambios silenciosos del parser); `coerce=False` asume que la limpieza previa ya coercionó.

> El contrato Pandera es **una pieza viva**: aceptar una nueva moneda o cambiar el límite máximo se hace en este fichero y solo aquí, queda versionado en git, y todo el pipeline downstream lo respeta. Es el `data_catalog.yaml` para datos.

## 4.5 La estrategia de fallo: reparar, cuarentena, descartar

Cuando una fila falla, hay tres respuestas según el tipo de fallo. La política debe ser **explícita y documentada**:

| Respuesta | Cuándo | Qué se hace |
|---|---|---|
| **Reparar automáticamente** | Fallo recuperable sin pérdida semántica (fecha `"15/03/2024"` con `dayfirst=True`; `"euros"` → `"EUR"`) | Pasada adicional de limpieza, **sin intervención humana** |
| **Cuarentena** | Fallo grave pero el registro podría servir tras revisión (`client_name` nulo con el resto completo; `total_amount` algo por encima del límite: ¿proyecto excepcional o typo?) | **No entra al RAG, pero se preserva** en tabla separada con su motivo, para que un humano decida |
| **Descartar** | Contaminación clara sin valor (`budget_id` que no cumple patrón = artefacto de migración; total negativo o 100× el límite) | **Se elimina con log detallado** |

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

1. **`lazy=True`** — Pandera recoge **todos** los errores del DataFrame y los devuelve juntos. Sin esto solo conoceríamos el primero y la política diferenciada sería ciega.
2. **El resultado siempre incluye `report`** — métricas para observabilidad (cuántos válidos, en cuarentena, qué fallos predominan). Es lo que **alerta cuando una fuente empieza a degradarse**, mucho antes de que llegue al RAG.

## 4.6 Trade-offs honestos del Artículo 4

- **Pandera vs Great Expectations.** Pandera es **ligera, en código Python, declarativa**: el schema vive con tu código y se versiona con él. Great Expectations es **más ambiciosa** (datadocs HTML auto-generados, profiling automático, integración con Airflow/Dagster) pero más pesada de operar. Para el Proyecto 2, Pandera (cero overhead de infra). Great Expectations tiene sentido con docenas de pipelines y stakeholders no técnicos.
- **Strict en producción vs permisivo en desarrollo.** El instinto correcto es el opuesto al esperado: **el schema es estricto desde el día 1**, y lo que se relaja es la **política ante fallos**, no el contrato. En desarrollo, cuarentena en vez de descartar permite ver los datos problemáticos sin romper el pipeline; en producción, descartar evita contaminar. **Si el contrato es laxo en desarrollo, los problemas aparecen el día del despliegue.**
- **Cuánto normalizar sin perder señal.** Normalizar agresivamente es peligroso: pasar todo a minúsculas resuelve "ACME Corp" vs "acme corp" pero borra "Apple" (empresa) vs "apple" (fruta). Regla: **normalizar con el bisturí, no con la motosierra.** Primero los casos de heterogeneidad claramente accidental (mayúsculas en monedas, espacios trailing, separadores de fecha); deja para después (o nunca) lo que podría borrar señal semántica.

---

# PARTE 5 — PII, anonimización y GDPR en el pipeline de ingest

El corpus ya pasó por inventario, extracción y validación. Pero contiene, sin excepción, **información personal y comercial sensible**: nombres de clientes en transcripciones, correos en presupuestos, teléfonos, IDs internos de proyecto que revelan estructura organizativa, condiciones contractuales que legal pidió no compartir.

## 5.1 El problema real: filtración semántica vía RAG

Intuición común a desmontar: muchos asumen que el **control de acceso** (autenticación, autorización, ACLs en la app) basta. Funciona en BBDD tradicionales. **No funciona en RAG**, por una razón estructural:

> En una BBDD relacional, para robar la columna `email` necesitas una query SQL que apunte a esa columna; si está protegida, no hay query que la devuelva. En RAG el ataque es **indirecto**: el usuario hace **preguntas en lenguaje natural**, el sistema busca semánticamente, recupera los chunks relevantes y se los pasa al modelo. Si los chunks contienen el dato sensible (literalmente, en el texto), el modelo lo usa. **No hay un nivel de permisos en el vector que pueda ocultarlo, porque el vector no sabe qué es sensible.**

Por eso la protección ocurre **antes** del embedding, no como filtro en la respuesta.

## 5.2 Los tres modos de filtración

| Modo | Qué es | Ejemplo |
|---|---|---|
| **Directa** | La más obvia. El dato sensible está literal en los chunks. | *"¿Qué clientes nos han contratado migraciones a cloud?"* → "Banco Sabadell, Inditex, Repsol". Trivial de explotar y de prevenir si la anonimización está en su sitio. |
| **Por agregación** | Cada query parece inocua; el atacante las combina. | *"¿Qué proyectos completamos en 2024?"* + *"¿el más caro?"* + *"¿en qué sector?"* + *"¿qué tecnologías?"*. Defenderse exige pensar en **superficie de información agregada**, no en chunks sueltos. |
| **Por inferencia** | La más peligrosa: ocurre **incluso tras anonimización ingenua**. | "Juan García, CEO de Acme" → "[PERSON], CEO de [ORG]" parece protegido, pero el sector + fechas + importes + geografía siguen ahí. La defensa no es solo anonimizar, sino **reducir la combinatoria de pistas que rodean al individuo**. |

> Las tres comparten algo: **ninguna requiere acceso administrativo.** Bastan credenciales legítimas y preguntas en lenguaje natural.

## 5.3 El marco GDPR mínimo aplicado al pipeline

> **GDPR** = el reglamento europeo que gobierna el tratamiento de datos personales.

Cuatro conceptos que cualquier AI Engineer en la UE necesita interiorizar:

- **Datos personales.** Definición amplia: cualquier información que identifique, directa o indirectamente, a una persona física. Obvios: nombres/emails/teléfonos. Menos obvios: **identificadores indirectos** (IP, cookie, número de empleado) y **combinaciones** que por separado no identifican pero juntas sí. En el Proyecto 2, las transcripciones son trivialmente datos personales, pero también pueden serlo presupuestos que combinan sector + importe + fecha + geografía si el conjunto reduce la población a un único cliente.
- **Anonimización vs pseudonimización.**
  - **Anonimización irreversible** — ni el operador puede recuperar el original; deja de ser "dato personal" a efectos de GDPR (con condiciones).
  - **Pseudonimización** — el dato real se sustituye por uno ficticio mediante un **mapping reversible** guardado por separado; **sigue siendo dato personal** (la mapping table lo es), pero su gestión es más simple. Para RAG suele ganar porque **preserva la coherencia semántica**: "Juan García" no se sustituye por `<PERSON>` (destruye estructura), sino siempre por "Carlos Martínez" en todo el corpus.
- **Derecho al olvido (art. 17).** Cualquiera puede pedir que se eliminen sus datos. En una BBDD es un `DELETE`; en RAG es un **problema arquitectónico**: los chunks que mencionan al individuo están vectorizados y dispersos. Sin un mapeo explícito "estos chunks contienen info sobre Juan García", la eliminación es imposible. (Otra razón por la que la mapping table es arquitectura, no detalle.)
- **Minimización.** Solo procesar los datos estrictamente necesarios. ¿Necesita el estimador los nombres reales de clientes? **No**: necesita los **patrones** de proyectos pasados (sector, alcance, tecnologías, complejidad), no la identidad. Esto justifica la pseudonimización agresiva desde el principio: no perdemos nada útil y eliminamos un riesgo.

## 5.4 Microsoft Presidio: detección y anonimización en pipeline

> **Presidio** = librería de Microsoft para detección y anonimización de PII.

Frente a alternativas (spaCy puro, nltk, AWS Comprehend), tiene tres bazas: arquitectura **modular** (`analyzer` + `anonymizer` intercambiables), **recognizers preconstruidos** para PII común (email, teléfono, IBAN, IPs, tarjetas, fechas, ubicaciones, personas, organizaciones) y soporte para **custom recognizers**.

Uso básico en dos pasos: el `analyzer` detecta entidades y posiciones; el `anonymizer` aplica una transformación.

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

> **Sin la configuración en español**, los falsos negativos en `PERSON` y `LOCATION` se disparan: no detecta nombres que para un hispanohablante son obvios. La operación `replace` con `[REDACTED]` es la más simple y **la peor para RAG** (destruye la estructura semántica); se muestra solo para ilustrar el flujo.

## 5.5 Recognizers custom para el dominio del Proyecto 2

Los recognizers default no conocen los identificadores propios del dominio. El Proyecto 2 tiene al menos dos:

- **Budget IDs** — patrón `BUDGET-YYYY-NNNN` (el invariante del schema Pandera del Artículo 4). No son PII estricta, pero revelan **info comercial sensible** (volumen de proyectos cerrados, numeración interna).
- **Códigos de cliente internos** — `CLI-1042`, `CLT-INT-A047`, que mapean uno-a-uno a clientes reales.

```python
budget_id_pattern = Pattern(name="budget_id_canonical",
    regex=r"\bBUDGET-\d{4}-\d{4}\b", score=0.95)
budget_id_recognizer = PatternRecognizer(supported_entity="BUDGET_ID",
    patterns=[budget_id_pattern], supported_language="es")
analyzer.registry.add_recognizer(budget_id_recognizer)
```

1. **`score` es decisivo** — la confianza con que el recognizer afirma haber detectado la entidad. Cuando varios se solapan, Presidio se queda con el de mayor score. Higiene: scores altos (0.9–0.95) en patrones específicos, bajos (0.4–0.6) en genéricos.
2. **El `supported_entity` declarado** (`BUDGET_ID`, `CLIENT_CODE`) es la **etiqueta semántica** que luego usa la pseudonimización para aplicar la transformación correcta (un budget ID → otro budget ID falso; un email → otro email).

Para nombres sin patrón regular ("Banco Sabadell", "Inditex"), herramienta complementaria: `RecognizerResult` cargados desde un **diccionario explícito** mantenido en el proyecto.

## 5.6 Pseudonimización reversible con Faker y una mapping table

> **Faker** = librería que genera datos ficticios realistas (nombres, emails, empresas).
> **Mapping table** = tabla que registra cada sustitución (original → pseudónimo) para poder revertirla.

La **pieza arquitectónica clave**: en lugar de tokens genéricos (`[PERSON]`), reemplazamos las entidades con **valores ficticios consistentes** generados por Faker, manteniendo en paralelo la mapping table.

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

1. **Consistencia por valor original, no por chunk.** "Juan García" siempre → "Carlos Martínez", aunque aparezca en cientos de chunks. Sin esto, dos chunks del mismo cliente acabarían lejos en el espacio vectorial y el retrieval volvería a romperse (la misma razón que la "heterogeneidad de formato" del Artículo 4).
2. **Generadores específicos por tipo de entidad.** Un nombre → otro nombre, no un email ni una fecha. Se preserva la señal semántica del tipo de campo.
3. **La mapping store es un componente separado**, encriptado, con su propio control de acceso. Si un auditor GDPR pregunta qué datos viven en tu sistema, la consulta es contra ese store, no contra el corpus vectorial.
4. **El `source_name` se persiste con el mapping** — permite responder "qué fuentes mencionan a esta persona" sin recorrer el índice vectorial.

> **Integración:** al final del pipeline de ingest, después de la validación (Artículo 4) y **antes del chunking (Sesión 7)**. El orchestrator toma cada `Document` validado, mira `metadata.contains_pii` (propagado desde el catálogo) y, si es `True`, aplica la pseudonimización. El `Document` resultante tiene el mismo `content` salvo los tokens reemplazados; el resto del pipeline no necesita saber nada de Presidio ni Faker.

## 5.7 El derecho al olvido en RAG: un caso práctico

Cuando alguien pide "quiero que mis datos no estén más en vuestro sistema de IA", con esta arquitectura son cinco pasos:

1. **Consultar la mapping store** con el nombre para identificar todos sus pseudónimos (pueden ser varios: nombre completo, nombre y apellido, alias).
2. **Buscar en el índice vectorial** los chunks que contienen esos pseudónimos o están asociados a documentos con esos pseudónimos en metadatos.
3. **Eliminar esos chunks** del índice.
4. **Eliminar las entradas correspondientes de la mapping store** — si la persona reaparece, recibirá un pseudónimo nuevo sin relación con el anterior.
5. **Registrar la operación en un audit log** que demuestre que se atendió en plazo y forma.

> Cada paso es trivial **gracias a la mapping table**. Sin ella, los pasos 1, 2 y 4 son imposibles y el sistema queda en incumplimiento permanente del art. 17. **La mapping table no es un detalle; es la pieza que sostiene el cumplimiento.**

## 5.8 Trade-offs honestos del Artículo 5

- **Anonimización irreversible vs pseudonimización reversible.** La irreversible es más simple (sustituir con `<PERSON>`, sin mapping store ni riesgo de filtración del mapping, ya no es "dato personal"). El problema: **los embeddings de un corpus con `<PERSON>` se degradan**. Pruebas internas: caídas del **15–25% en métricas de retrieval** con sustitución genérica. Para producción con compromiso de calidad, la pseudonimización reversible es casi siempre lo correcto. La irreversible queda para corpus "públicos por defecto" o casos donde un contrato legal lo exige.
- **Falsos positivos de Presidio en español.** Funciona bastante peor que en inglés. `es_core_news_md` etiqueta nombres comunes como `PERSON` con frecuencia molesta ("Mar", "Sol", "Cruz", "Alba"). Tres mitigaciones: subir el umbral de score (0.5 → 0.7 reduce falsos positivos a costa de algún falso negativo), añadir una **blacklist** de palabras que no son PII, y entrenar un NER customizado si el volumen lo justifica. Para el Proyecto 2, las dos primeras bastan.
- **Impacto en la calidad de los embeddings.** La pseudonimización consistente preserva la mayor parte de la señal, pero introduce algo de ruido: un nombre real lleva micro-información que un falso no replica (origen geográfico, género percibido, frecuencia en el corpus). Para un RAG de estimación es despreciable (el retrieval va por patrones de proyecto, no por identidad). Para sistemas donde la identidad importa (asistentes personales, CRM), el coste es mayor. Regla: **pseudonimizar primero, medir después** con queries representativas, decidir caso por caso si algún tipo de entidad (rara vez) merece dejarse sin tratar.

---

# Chuleta de una página

| Artículo | Lo imprescindible |
|---|---|
| **1 — Por qué RAG, no CAG** | El techo del CAG son **4 restricciones simultáneas**: context window, coste/consulta, latencia y **degradación de atención** (*lost in the middle*). Basta que una falle. La calidad del dato es la **variable de control**: basura entra, basura sale. |
| **Offline vs online** | **Dos pipelines, no uno.** Offline (ingest→parse→chunk→embed): background, minutos-horas, modelos pesados. Online (retrieve→augment→generate): síncrono, <3s, quirúrgico. **No mezclarlos.** |
| **Árbol de decisión (4 ejes)** | Trazabilidad o acceso por usuario → RAG. No cabe (>70% del contexto) → RAG. Cambia <7 días → RAG. Estable (>90 días) y pequeño (<30%) → CAG. Resto → **híbrido**. Fine-tuning ≠ alternativa: es capa encima. |
| **2 — Audita antes de vectorizar** | Censo (nombre lógico, owner, formato, volumen, periodicidad **declarada vs observada**). Calidad en 4 dimensiones (completitud, consistencia, actualidad, fiabilidad) **sin promediar**. Linaje contra la **context erosion**. |
| **El catálogo es código** | `data_catalog.yaml` versionado + loader Pydantic. Decisión `include/exclude/review` por fuente. Excluir fuentes malas es **disciplina**, no desidia. |
| **3 — `Document` canónico** | `content` + `metadata` como contrato. Arquitectura `ingest/`: **loaders** (acceso) → **parsers** (formato, representación intermedia) → **normalizers** (a Document). Tres capas por testabilidad. |
| **Parsing por formato** | JSON → markdown estructurado (no `json.dumps`). TXT → turnos con speaker. XLSX → tabla markdown si es tabla pura. DOCX → un Document por sección/heading. PDF → `pypdf` por defecto, `unstructured hi_res` solo si tablas/escaneo. |
| **4 — Limpieza ≠ validación** | Cuatro suciedades: heterogeneidad, duplicados con divergencia, nulos disfrazados, valores fuera de rango. Capa **entre parser y normalizer**. pandas normaliza (coerciones permisivas → `NaN`); **Pandera** valida (`strict=True`, cross-column, `lazy=True`). Política: **reparar / cuarentena / descartar**. |
| **5 — PII antes del embedding** | El control de acceso **no** protege en RAG (filtración semántica: directa / agregación / inferencia). GDPR: datos personales (amplio), anon vs **pseudo** (gana pseudo por coherencia semántica), derecho al olvido (art. 17), minimización. |
| **Presidio + Faker + mapping table** | Config NLP en español (`es_core_news_md`). Custom recognizers (`BUDGET_ID`, `CLIENT_CODE`) con `score`. **Pseudonimización consistente por valor original** (mismo nombre → mismo pseudónimo). La **mapping table encriptada** sostiene el derecho al olvido. Sustitución genérica `<PERSON>` cuesta **15–25%** de retrieval. |

---

## Cómo conecta con nuestro ejercicio y con el directo

Esta sesión es **el cimiento del Módulo 3** y de todo el bloque RAG del Proyecto 2 (el estimador). El corpus pasa por **cinco decisiones acumulativas**:

1. **Artículo 1** — Justificada la transición de CAG a RAG (con capa híbrida residual de CAG para el contexto estable: glosarios, plantillas, tarifas).
2. **Artículo 2** — Catálogo versionado de fuentes (`data_catalog.yaml`) con políticas explícitas de inclusión/exclusión y reporte de auditoría.
3. **Artículo 3** — Subsistema `ingest/` (loaders → parsers → normalizers) con el `Document` canónico como contrato.
4. **Artículo 4** — Capa de limpieza (pandas) y validación (Pandera) como guardián de los invariantes de negocio, con la política reparar/cuarentena/descartar.
5. **Artículo 5** — Anonimización con Presidio + mapping table que sostiene el cumplimiento GDPR.

> Al final no tenemos código brillante; tenemos **un corpus que un equipo de producción podría defender ante cualquier interlocutor** (legal, comercial, técnico, regulatorio). Cada decisión versionada, cada exclusión con motivo, cada dato sensible con mapping reversible, cada invariante con un schema que lo hace cumplir.

**Hacia delante:** en la **Sesión 7** se ataca la vectorización (embeddings, chunking, modelos, espacio vectorial); en la **Sesión 8**, las bases vectoriales y pgvector. La calidad de este cimiento determina cuánto vale el sistema final en producción.

> **Divergencias de nuestra implementación** (ver memorias de proyecto): la sesión oficial asume Drive/Dropbox/S3 como fuentes y un stack genérico; nuestro estimador porta el pipeline a **single-Postgres** con `psycopg` v3 (no psycopg2) y `DbSessionStore`. La ingesta, la limpieza Pandera y la anonimización Presidio se **adaptan** a esas divergencias, no se copian literalmente.
