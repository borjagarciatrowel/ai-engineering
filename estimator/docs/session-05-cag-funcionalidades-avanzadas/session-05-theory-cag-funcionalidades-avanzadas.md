# Sesión 5 — Teoría: contexto dinámico, memoria conversacional, prompts por perfil (tier), evaluación de LLMs y el patrón Actor-Critic-Boss

> Resumen unificado de los cinco artículos teóricos de la sesión 05 del programa *AI Engineering 2026* (Antonio Pérez / LIDR). Cada PARTE corresponde a un artículo, en el orden 01 → 05. El hilo conductor es el mismo proyecto del curso: el **`estimator`**, un servicio de IA que produce estimaciones de software a partir de transcripciones de reuniones.
>
> Documento pensado para estudiar la teoría subyacente. Los apartados marcados **(para cualquiera)** están escritos sin jerga para que se entiendan sin background técnico.

---

## 0. La idea en una página (para cualquiera)

Hasta la sesión 04, el `estimator` funcionaba como una máquina de un solo botón: le metes una transcripción, monta un prompt fijo, y el modelo de lenguaje (LLM) devuelve una estimación. Todo el "conocimiento" que usaba estaba escrito a mano dentro del código. Eso funciona en el laboratorio, pero se rompe en cuanto el sistema sale al mundo real. La sesión 05 cubre las cinco piezas que convierten ese prototipo en un producto serio:

1. **Traer información de fuera en tiempo real (contexto dinámico).** Nadie estima un proyecto solo con una transcripción: hay un PDF de especificación, precios actuales de servicios cloud, un histórico de proyectos parecidos en la base de datos de la empresa. La PARTE 1 explica los tres mecanismos canónicos para incorporar todo eso —**adjuntos, búsqueda web y consultas a la base de datos del negocio**— y, sobre todo, cuándo activar cada uno (porque cada uno cuesta dinero y añade lentitud).

2. **Recordar de qué va la conversación (memoria).** Si hablas con el sistema durante veinte turnos sobre un proyecto, esperas que recuerde su nombre, las tecnologías acordadas y el equipo, sin repetirlos cada vez. La PARTE 2 distingue dos cosas que la gente confunde: el **historial** (lo que se dijo, palabra por palabra) y la **memoria** (los hechos destilados que importan). Mantenerlas separadas es lo que evita que el sistema "se olvide" de cosas.

3. **Responder distinto según quién pregunta (patrón "tier").** Un desarrollador y un director comercial piden la misma estimación pero necesitan formatos completamente distintos. La PARTE 3 muestra que esto no requiere inteligencia artificial avanzada: se resuelve con una columna en una base de datos y un selector de plantilla. Es desarrollo web normal.

4. **Saber si el sistema funciona (testing y evaluación).** El test clásico `assert resultado == "16 horas"` no sirve, porque el mismo input puede dar 14, 16 o "rango 10-22". La PARTE 4 enseña a testear **propiedades** en lugar de igualdad exacta, con tres familias de tests y un "golden dataset" de casos curados.

5. **Subir el techo de calidad (Actor-Critic-Boss).** Por mucho que afines el prompt, hay un límite de calidad que no se rompe. La PARTE 5 introduce un patrón de tres roles —uno **genera**, otro **critica**, otro **decide**— que imita cómo un humano revisa su propio trabajo antes de entregarlo, y que sube la calidad de forma medible.

El hilo común de las cinco partes: **la sofisticación de un sistema de IA bien hecho casi nunca vive en el modelo; vive en la arquitectura que lo rodea.** Y casi siempre la regla operativa es la misma: *no añadas potencia por defecto; añádela cuando tengas evidencia de que el sistema la necesita, y mide siempre el coste en tokens y latencia.*

---

# PARTE 1 — Integración de contexto dinámico desde fuentes externas

## 1.1 La distinción crítica: contexto estático vs contexto dinámico

Hasta ahora todo el contexto que viajaba al LLM era **estático**: vivía en código (templates Jinja2, ejemplos hardcoded en el system prompt) o en parámetros tipados que producía el formulario. Es predecible, versionable y testeable.

El contexto **dinámico** es el que el sistema obtiene **en tiempo de ejecución**, en respuesta a una petición concreta. No vive en código; vive en sistemas externos: el sistema de archivos del usuario, la web, una BBDD, un sistema de tickets.

> **(para cualquiera)** Estático = lo que el equipo de producto escribió de antemano y no cambia entre peticiones. Dinámico = lo que el sistema va a buscar en el momento porque depende de lo que el usuario acaba de pedir. Un PDF que sube el usuario, el precio de hoy de un servidor en AWS, o los proyectos parecidos que hizo la empresa el año pasado son contexto dinámico.

## 1.2 Las tres reglas del contexto dinámico

Antes de tocar ningún mecanismo, hay que interiorizar tres reglas operativas:

- **Regla 1 — El contexto dinámico es _input_, no _programa_.** Tratarlo como código (concatenarlo a ciegas en el prompt, dejar que el usuario inyecte instrucciones disfrazadas de adjunto) es la receta para el **prompt injection** clásico. Cualquier contenido que entra desde fuera de tu sistema debe estar **claramente delimitado** en el prompt, y nunca se le da al LLM la capacidad de interpretarlo como instrucciones.
- **Regla 2 — El contexto dinámico tiene coste real por petición.** Mientras el estático se paga una vez en *token caching*, el dinámico se reincluye en cada llamada y consume tokens nuevos. Adjuntar un PDF de 30 páginas en cada turno duplica fácilmente el coste de la sesión.
- **Regla 3 — El contexto dinámico introduce latencia que tu usuario nota.** Procesar un PDF puede llevar 1–3 s. Una búsqueda web añade 2–5 s. Consultar la BBDD del backend, otro round-trip. La diferencia entre un producto que se siente vivo y uno que se siente roto está aquí.

A partir de esas tres reglas, hay **tres mecanismos canónicos** para enriquecer un sistema CAG en runtime **sin saltar todavía a una arquitectura RAG**.

## 1.3 Mecanismo 1 — Archivos adjuntos

El usuario sube un PDF con la especificación técnica del proyecto y el servicio IA tiene que incorporar ese contenido. Hay **dos caminos canónicos**, y la elección no es trivial:

| | **Camino A — Multimodal directo** | **Camino B — Extracción local** |
|---|---|---|
| Flujo | PDF → Files API del proveedor → LLM multimodal (texto + diagramas) | PDF → extracción local (`pypdf`, `PyMuPDF`, `Docling`) → LLM (cualquiera, solo texto) |
| Ventajas | Cero código de extracción; interpreta diagramas e imágenes | Independiente del proveedor; control fino del contenido; **prepara el terreno para RAG** |
| Desventajas | Acoplado al proveedor multimodal; consume más tokens | Código que mantener; pierde la información visual |

**Camino A — el PDF viaja al LLM.** Los proveedores grandes (Anthropic, OpenAI) tienen soporte nativo de PDFs. Subes el archivo a la Files API y lo referencias en el bloque de contenido del mensaje:

```python
import anthropic

client = anthropic.Anthropic()

with open("specification.pdf", "rb") as f:
    uploaded = client.beta.files.upload(
        file=("specification.pdf", f, "application/pdf"),
    )

response = client.beta.messages.create(
    model="claude-opus-4-7",
    max_tokens=2048,
    betas=["files-api-2025-04-14"],
    messages=[
        {
            "role": "user",
            "content": [
                {"type": "document", "source": {"type": "file", "file_id": uploaded.id}},
                {"type": "text", "text": "Use this technical specification as additional context."},
            ],
        },
    ],
)
```

La latencia de carga se paga **una sola vez** (la Files API mantiene el archivo durante la conversación) y el resto de turnos referencian el `file_id`. La pega: estás **acoplado al proveedor multimodal**; el modelo tokeniza tanto el texto como una representación visual de cada página (más tokens); y tienes menos control sobre qué partes del documento entran (todo o nada).

**Camino B — solo el texto viaja al LLM.** Extraes el contenido en tu servicio IA *antes* de la llamada y envías solo texto:

```python
from pypdf import PdfReader
from io import BytesIO

def extract_text_from_pdf(file_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(file_bytes))
    parts = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        parts.append(f"--- Page {index} ---\n{text}")
    return "\n\n".join(parts)
```

Luego concatenas con un **delimitador claro** que el LLM reconozca:

```python
user_prompt = f"""
<transcript>
{transcript}
</transcript>

<attachments>
{attachments_block}
</attachments>

Produce a software estimate based on the transcript. Use the attachments as context.
"""
```

Para PDFs nativos de texto, `pypdf`/`PyMuPDF` bastan; para escaneados o con layout complejo, `Docling`/`MarkItDown`/`LlamaParse` producen markdown estructurado (conservan tablas y jerarquía) usando internamente modelos multimodales. Para Word existe `python-docx`. La ventaja decisiva: **la lógica de extracción que escribes hoy es exactamente la primera pieza del pipeline de chunking de RAG** (módulo 3).

**Cómo elegir.** Ambos caminos son defendibles. Si prima la velocidad de desarrollo y no te importa el lock-in: camino A. Si quieres entender el flujo completo de procesamiento de documentos y prepararte para RAG: camino B. **Lo que NO se hace es implementar los dos en paralelo** — es una decisión arquitectónica, no una característica que se acumule.

## 1.4 Mecanismo 2 — Búsqueda web

Necesario cuando la estimación involucra tecnologías, precios o benchmarks que el modelo no tiene en su corte de conocimiento (ej.: "queremos usar Bun en lugar de Node"). Hay **tres aproximaciones**:

- **Aproximación 1 — Herramienta nativa del proveedor.** OpenAI y Anthropic exponen búsqueda web como *tool* de primera clase. La habilitas y el modelo decide cuándo usarla:
  ```python
  response = client.responses.create(
      model="gpt-4.1",
      input=user_prompt,
      tools=[{"type": "web_search"}],
  )
  ```
  Lo más simple y mejor integrado con el razonamiento del modelo. La pega: **lock-in total** y la calidad depende del índice del proveedor, que no controlas.
- **Aproximación 2 — Servicio de búsqueda independiente** (**Tavily**, **Exa**, **Firecrawl**). Devuelven resultados optimizados para consumo por LLMs: snippets más largos, markdown limpio, ranking semántico. Lo expones como una *tool* que defines tú:
  ```python
  from tavily import TavilyClient

  tavily = TavilyClient(api_key=settings.tavily_api_key)

  def web_search(query: str, max_results: int = 5) -> list[dict]:
      results = tavily.search(query=query, max_results=max_results)
      return [
          {"title": r["title"], "url": r["url"], "snippet": r["content"]}
          for r in results["results"]
      ]
  ```
  Ventaja: independencia del proveedor, mismo wrapper para cualquier LLM. Pega: cableas tú el function calling, mantienes otra clave, pagas otra factura.
- **Aproximación 3 — SERP API tradicional** (`SerpAPI`, `Serper`). Devuelven resultados crudos de Google/Bing; tú haces el fetch, la limpieza y el resumen. Máximo control, máxima carga de mantenimiento. Para el `estimator` rara vez compensa.

**Cuándo activar la búsqueda.** Solo cuando el system prompt no pueda responder con información del propio modelo **y** la pregunta sea sensible al tiempo: tecnologías recientes (últimos 6 meses), comparativas de precios SaaS, benchmarks recientes de hardware/cloud, disponibilidad de librerías concretas. Para todo lo demás (patrones arquitectónicos, prácticas de equipo, riesgos típicos), el modelo ya lo sabe y activar búsqueda **solo añade ruido**.

## 1.5 Mecanismo 3 — Consultas a la BBDD del backend de negocio

El más interesante arquitectónicamente. Cuando el sistema estima, quieres que considere los **proyectos similares que la empresa hizo antes** (horas reales, desviaciones, riesgos materializados). Esos datos viven en la BBDD del backend de negocio, **no** en el servicio IA.

**Qué NO hacer: dar al servicio IA acceso directo a la BBDD del negocio.** Es un error arquitectónico caro:
- **Acoplamiento de schema:** el servicio IA acaba conociendo el modelo de datos interno; cualquier cambio rompe ambos.
- **Permisos:** el servicio IA termina con credenciales de BBDD demasiado amplias y persistentes.
- **Lógica duplicada:** las reglas de negocio (qué proyectos cuentan, cómo agregar horas) acaban implementadas en dos sitios.

> Cuando lleguemos a RAG (módulo 3), la BBDD vectorial **sí** vivirá cerca del servicio IA — pero esa es la BBDD de **conocimiento del servicio IA**, no la **BBDD operacional del backend de negocio**. La distinción importa.

**Qué SÍ hacer: function calling contra el backend de negocio.** Expresas la consulta como una *herramienta* que el LLM invoca; la implementación hace una llamada HTTP autenticada al backend, que resuelve contra su propia BBDD y devuelve un payload limpio.

```
LLM
 │  (decide invocar tool)
 ▼
Servicio IA (Python)
 │  (llamada HTTP autenticada)
 ▼
Backend de negocio (Rails u otro stack)
 │  (consulta su BBDD aplicando reglas de negocio)
 ▼
PostgreSQL del backend de negocio
```

El servicio IA define la herramienta y la implementa como cliente HTTP:

```python
similar_projects_tool = {
    "type": "function",
    "function": {
        "name": "find_similar_projects",
        "description": (
            "Find historical projects with similar scope, technologies, team size. "
            "Returns aggregated metrics on actual hours, deviations and risks."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "technologies": {"type": "array", "items": {"type": "string"}},
                "team_size": {"type": "integer"},
                "scope_summary": {"type": "string"},
            },
            "required": ["technologies", "scope_summary"],
        },
    },
}

async def find_similar_projects(technologies, scope_summary, team_size=None) -> dict:
    response = await http_client.post(
        f"{settings.business_backend_url}/api/internal/similar_projects",
        json={"technologies": technologies, "scope_summary": scope_summary, "team_size": team_size},
        headers={"Authorization": f"Bearer {settings.internal_api_token}"},
    )
    response.raise_for_status()
    return response.json()
```

El backend de negocio expone el endpoint interno (aquí Rails, pero el patrón es **independiente del stack**: vale Rails, NestJS, Spring, Django o Go):

```ruby
# app/controllers/internal/similar_projects_controller.rb
module Internal
  class SimilarProjectsController < InternalApiController
    def create
      similar = Project.completed
        .with_any_technology(params[:technologies])
        .with_scope_similar_to(params[:scope_summary])
        .limit(5)
      render json: { projects: similar.map { |p| ProjectMetricsSerializer.new(p).as_json } }
    end
  end
end
```

**Por qué este patrón es el correcto.** Preserva las tres capas limpias: el servicio IA no sabe nada del schema de proyectos (solo que existe la tool `find_similar_projects`); el backend mantiene la autoridad sobre las reglas de negocio; la BBDD operacional sigue accediéndose solo desde donde debe. **El servicio IA y el backend se hablan por contrato HTTP, nunca por BBDD compartida** — y esa regla se mantiene incluso cuando entre RAG.

## 1.6 Combinando los tres: agentic loop, budget y trazabilidad

En un caso real, los tres mecanismos coexisten en una misma petición: el usuario sube transcripción + PDF (mec. 1), el LLM decide que necesita precios actuales de AWS (mec. 2) y consulta proyectos similares (mec. 3) antes de estimar.

```
Fuentes externas            Orquestación              Generación
┌──────────────────┐
│ Archivos adjuntos│──┐
│ (PDF, Word, img) │  │
└──────────────────┘  │     ┌────────────────┐      ┌─────────────┐
┌──────────────────┐  ├────▶│   Servicio IA  │─────▶│     LLM     │
│  Búsqueda web    │──┤     │ Python+FastAPI │      │ Razonamiento│
│  (datos recientes)│ │     └────────────────┘      └─────────────┘
└──────────────────┘  │
┌──────────────────┐  │
│  BBDD del negocio│──┘
│ (histórico,      │
│  catálogo)       │
└──────────────────┘
```

El patrón que orquesta esto es el **agentic loop** que la Responses API ya implementa por defecto: el LLM razona, decide qué herramienta invocar, recibe resultados, razona de nuevo, y o bien llama otra tool o produce la respuesta final. Tú expones las herramientas y dejas que el modelo decida la secuencia.

Dos disciplinas obligatorias en producción:
- **Budget de tokens.** La suma de system prompt + transcript + adjuntos + búsqueda + BBDD puede reventar la ventana de contexto. Define un máximo por turno y aplica truncado/resumen al superarlo.
- **Trazabilidad.** Cada tool invocada es un nuevo *span* observable. Conéctalo a la observabilidad estructurada de la sesión 03 (`structlog` + Logfire/Langfuse). Un turno deja de ser una llamada al LLM y pasa a ser un **grafo de invocaciones** que necesita visibilidad de extremo a extremo.

## 1.7 Resumen: cuándo cada mecanismo

| Mecanismo | Cuándo usarlo | Coste principal | Latencia añadida |
|---|---|---|---|
| **Adjuntos** | El usuario aporta documentación específica para esta petición | Tokens del documento procesado | 1–3 s por documento |
| **Búsqueda web** | La pregunta es sensible al tiempo o requiere datos posteriores al corte de entrenamiento | Tokens de los snippets + factura del proveedor | 2–5 s por query |
| **BBDD del backend** | La respuesta debe basarse en datos propios de la empresa (histórico, catálogo, clientes) | Round-trip HTTP + tokens del payload | 100–500 ms por consulta |

**Las dos preguntas antes de añadir cualquier mecanismo:** ¿el modelo *podría* responder bien sin esto, o sin esto va a fallar de forma sistemática? Y ¿la latencia añadida degrada la experiencia más que el valor que aporta? El instinto "añade más contexto, no puede hacer daño" es falso: más contexto = más tokens, más latencia, más superficie de prompt injection, más complejidad de debugging. **Arranca con el mínimo necesario y añade contexto dinámico solo con evidencia.**

---

# PARTE 2 — Memoria conversacional vs historial: estrategias para sistemas CAG

## 2.1 Definiciones operativas

En la sesión 02 todo era "historial" y la palabra "memoria" aparecía como sinónimo aproximado. Esa elipsis era deliberada, pero se rompe al introducir conversaciones multi-turno sobre un proyecto en curso. Son **dos cosas distintas**:

- **Historial conversacional** = el array de mensajes (`system`, `user`, `assistant`, `user`, `assistant`…) que viaja a la API en cada llamada. Es una estructura **bruta**: cada mensaje contiene exactamente lo que se escribió, en orden cronológico. Responde a *"¿qué dijo el usuario en el turno 7?"*.
- **Memoria conversacional** = el conjunto de **hechos destilados** que el sistema ha aprendido del dominio a lo largo de los turnos. No son turnos; son afirmaciones: *"el proyecto se llama BookFlow"*, *"el equipo asumido son 3 personas full-time"*, *"el cliente rechazó microservicios para la fase 1"*. Cada hecho tiene un origen, pero **la memoria es independiente del turno: persiste aunque el turno original se haya descartado**. Responde a *"¿qué sabemos sobre este proyecto?"*.

> **(para cualquiera)** El historial es la transcripción literal de la conversación. La memoria es la ficha de resumen del proyecto que vas rellenando. Si tiras turnos viejos para ahorrar (cosa que hay que hacer), la transcripción se acorta pero la ficha sobrevive — y por eso el sistema no "se olvida".

**Por qué las dos por separado:**
- **Coste y latencia.** El historial crece linealmente; la memoria no (un proyecto puede tener 20 hechos tras 100 turnos). Reenvías los hechos en cada llamada sin pagar el historial completo.
- **Resistencia al truncado.** Si la memoria depende del historial, desaparece al truncar. Si es independiente, sobrevive.
- **Auditabilidad.** En producción te preguntarán "¿por qué el LLM asumió X?". Si los hechos están en una estructura inspeccionable, puedes responder.

## 2.2 Anatomía del estado conversacional

Una sesión del `estimator` tiene **tres componentes de estado**, no uno:

```
Session (objeto raíz)
├── session_id: UUID v4
├── history (lo bruto)              ── crece linealmente, sufre truncado de ventana
│     ├── system: rol y contexto CAG
│     ├── user: turno N-2
│     ├── assistant: turno N-2
│     └── user: turno N-1
└── project_metadata (lo destilado) ── crece solo con hechos nuevos, sobrevive al truncado
      ├── project_name: BookFlow
      ├── assumed_team_size: 3
      ├── technologies: Rails, React
      ├── agreed_scope: MVP fase 1
      └── rejected_options: microservicios
```

```python
from pydantic import BaseModel, Field
from datetime import datetime
from uuid import uuid4

class ProjectMetadata(BaseModel):
    """Distilled facts about the project under estimation.
    Survives history truncation. Updated after each turn."""
    project_name: str | None = None
    assumed_team_size: int | None = None
    mentioned_technologies: list[str] = Field(default_factory=list)
    agreed_scope: str | None = None
    explicit_constraints: list[str] = Field(default_factory=list)
    rejected_options: list[str] = Field(default_factory=list)

class Message(BaseModel):
    role: str  # "system" | "user" | "assistant"
    content: str

class Session(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    history: list[Message] = Field(default_factory=list)
    project_metadata: ProjectMetadata = Field(default_factory=ProjectMetadata)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
```

La separación es **estructural**, no decorativa. En cada turno el sistema hace tres cosas en orden:
1. **Inyecta** `project_metadata` en el system prompt vía template Jinja2, junto con la ventana actual de `history`.
2. **Llama** al LLM y obtiene la respuesta.
3. **Actualiza** tanto `history` (añadiendo el par user/assistant) como `project_metadata` (extrayendo hechos nuevos).

Los pasos 1 y 3 son donde vive la pieza interesante; el paso 2 es la llamada que ya conoces.

## 2.3 Inyectar la memoria en el system prompt

El template Jinja2 recibe un bloque `<project_metadata>` con los hechos conocidos. Arranca vacío y se va poblando:

```jinja2
You are a senior software estimation expert. Produce realistic, well-justified
estimates for software projects based on meeting transcripts and complementary documentation.

{% if project_metadata %}
<project_metadata>
{% if project_metadata.project_name %}Project name: {{ project_metadata.project_name }}{% endif %}
{% if project_metadata.assumed_team_size %}Assumed team size: {{ project_metadata.assumed_team_size }} full-time engineers{% endif %}
{% if project_metadata.mentioned_technologies %}Technologies mentioned: {{ project_metadata.mentioned_technologies | join(", ") }}{% endif %}
{% if project_metadata.agreed_scope %}Agreed scope: {{ project_metadata.agreed_scope }}{% endif %}
{% if project_metadata.rejected_options %}Rejected options (do not propose these again): {% for option in project_metadata.rejected_options %}{{ option }} {% endfor %}{% endif %}
</project_metadata>
{% endif %}

<context_examples>{% include "reference_estimates.j2" %}</context_examples>

When producing the estimate, treat the project_metadata as established facts.
Do not contradict them unless the user explicitly revises them in the current turn.
```

Dos detalles clave:
- **Renderizado condicional.** Cada campo se incluye solo si tiene valor. Evita que el LLM vea `Project name: None`, lo cual ensucia el contexto e induce a inventar valores.
- **Tratamiento explícito como hechos establecidos.** La instrucción *"treat the project_metadata as established facts"* no es decorativa: sin ella, el LLM trata la memoria como una sugerencia más y renegocia hechos ya cerrados. Con ella, la memoria tiene **autoridad** sobre interpretaciones nuevas. Resultado: aunque el turno donde se dijo "vamos a usar Rails" haya caído de la ventana, el hecho `mentioned_technologies: ["Rails"]` sigue ahí y el modelo no vuelve a preguntar el stack.

## 2.4 Actualizar la memoria después de cada turno

Inyectar es fácil; **mantenerla viva** es la pieza interesante. Hay dos aproximaciones con perfiles de coste/robustez muy distintos:

**Aproximación 1 — Heurística simple.** Reglas explícitas (regex, vocabulario conocido) que extraen hechos del turno:

```python
import re

KNOWN_TECHNOLOGIES = {"rails", "react", "postgresql", "redis", "node", "python", ...}

def update_metadata_heuristic(metadata: ProjectMetadata, user_turn: str, assistant_turn: str) -> ProjectMetadata:
    combined = f"{user_turn}\n{assistant_turn}".lower()

    # Project name: simple regex
    if metadata.project_name is None:
        match = re.search(r"(?:project (?:is )?(?:called|named) )['\"]?([A-Za-z0-9]+)", combined)
        if match:
            metadata = metadata.model_copy(update={"project_name": match.group(1)})

    # Technologies: vocabulary match
    found = {tech for tech in KNOWN_TECHNOLOGIES if tech in combined}
    if found:
        merged = sorted(set(metadata.mentioned_technologies) | found)
        metadata = metadata.model_copy(update={"mentioned_technologies": merged})

    return metadata
```
- *Ventajas:* coste cero por turno (sin llamada extra al LLM), latencia despreciable, comportamiento predecible y depurable.
- *Desventajas:* **frágil**. La regex asume una formulación concreta en inglés; "let's call it Bookflow internally" no la captura. Las heurísticas crecen en complejidad y acaban siendo un pequeño NLP propio difícil de mantener.

**Aproximación 2 — LLM extractor.** Una segunda llamada al LLM con un prompt específico que devuelve el `ProjectMetadata` actualizado en JSON:

```python
EXTRACTION_PROMPT = """
You receive the current ProjectMetadata of a software estimation session and the latest
conversation turn. Produce an updated ProjectMetadata that incorporates any new facts.

Rules:
- Only update fields when the turn provides clear evidence.
- Preserve existing values unless the user explicitly revises them.
- If the user retracts a previous fact, remove it.
- For lists (technologies, constraints, rejected_options), append new items without duplicating.

Current metadata: {current_metadata_json}
Latest turn: USER {user_turn} ASSISTANT {assistant_turn}

Return ONLY a valid JSON matching the ProjectMetadata schema.
"""

async def update_metadata_llm(metadata, user_turn, assistant_turn, client) -> ProjectMetadata:
    response = await client.responses.create(
        model="gpt-4o-mini",
        input=EXTRACTION_PROMPT.format(
            current_metadata_json=metadata.model_dump_json(),
            user_turn=user_turn,
            assistant_turn=assistant_turn,
        ),
        response_format={"type": "json_object"},
    )
    return ProjectMetadata.model_validate_json(response.output_text)
```
- *Ventajas:* robusto ante variaciones de lenguaje, multilingüe sin trabajo extra, captura hechos sutiles. Reutiliza el patrón de datos estructurados con schema de la sesión 04.
- *Desventajas:* una llamada extra al LLM por turno (coste en céntimos, no cero), latencia +500–1500 ms, y un **riesgo nuevo**: si el extractor inventa un hecho falso, contamina todas las llamadas siguientes.

**Cómo elegir:** dominio acotado y formulaico → heurística. Dominio abierto/multilingüe → LLM extractor. Con presupuesto para ambos → LLM extractor + validación heurística posterior que descarte extracciones obviamente erróneas. Para el `estimator` (conversación libre y posiblemente bilingüe) la balanza se inclina ligeramente hacia el **LLM extractor**, pero la heurística es defendible si quieres minimizar coste y latencia.

## 2.5 La estrategia de gestión de historial vuelve (y se simplifica)

Las tres estrategias canónicas de la sesión 02:

| Estrategia | Cómo funciona | Cuándo elegirla |
|---|---|---|
| **Ventana deslizante** | Mantiene los últimos N turnos, descarta los antiguos | Conversaciones cortas, o cuando los hechos ya están en `project_metadata` |
| **Resumen acumulativo** | Resume los turnos antiguos en un único mensaje compacto | Conversaciones largas donde los matices del lenguaje original importan |
| **Híbrida con anclas** | Resumen de lo antiguo + ventana de los últimos N + turnos críticos que nunca se descartan | Producción seria, conversaciones de días o semanas |

**La consecuencia práctica más importante de separar memoria e historial:** la decisión de qué estrategia usar se vuelve **menos crítica**. La ventana deslizante simple deja de ser arriesgada porque los hechos que importan ya no se pierden al caer un turno — viven en la memoria, que es independiente. **Ventana deslizante con `MAX_TURNS = 6` + `project_metadata` actualizado por turno es una arquitectura completamente razonable para producción inicial.**

## 2.6 Cuándo olvidar: tres políticas explícitas

Sin políticas de olvido, la memoria crece sin control y los hechos viejos contaminan decisiones nuevas. Tres políticas, **tres ubicaciones distintas** en la arquitectura:

- **Política 1 — Revisión explícita por el usuario.** Si dice "ya no vamos a usar Rails, vamos con Node", la memoria debe reflejarlo (`mentioned_technologies` actualizada, `rejected_options` ampliada con "Rails"). Vive en la **lógica de actualización de memoria**.
- **Política 2 — TTL por sesión.** Una sesión inactiva 24 h probablemente ya no es la misma conversación de negocio; reanudar con memoria antigua induce asunciones erróneas. Se archiva y al reanudar se ofrece sesión nueva (con memoria heredada o desde cero). Vive en el **ciclo de vida de la sesión** (job programado).
- **Política 3 — Reset explícito.** El usuario debe poder decir "olvida todo y empezamos de cero". Un endpoint `POST /sessions` crea una sesión limpia, dejando la anterior intacta para auditoría. Es un **endpoint REST** normal.

La tentación es tratar el olvido como una sola pieza; la realidad es **tres mecanismos independientes** que conviene mantener separados.

## 2.7 Persistencia y anti-patrones

**Persistencia (lo que no entra todavía).** En una arquitectura madura las sesiones viven en BBDD persistente (Redis para acceso rápido, PostgreSQL para auditoría) gestionada por el backend de negocio; el servicio IA recibe el `session_id` y carga el estado. En la fase actual del programa, la elección razonable es un **diccionario en memoria** del proceso del servicio IA: simple, no escala más allá de un proceso, se pierde al reiniciar. Se acepta porque persistencia y federación pertenecen al módulo de despliegue. Lo importante: **la separación `history` / `project_metadata` sobrevive intacta al introducir persistencia** — ambos se serializan independientemente; migrar de dict a Redis no requiere refactor del modelo.

**Anti-patrones frecuentes:**
- **AP1 — Memoria en el system prompt como string libre.** Bloque de texto plano actualizado a mano. Funciona en el turno 1; en el turno 20 está lleno de inconsistencias. Una estructura tipada es más larga pero infinitamente más mantenible.
- **AP2 — Confiar en que el LLM "se acordará".** El LLM **no tiene estado entre llamadas**. Si el turno cayó de la ventana, el hecho desaparece salvo que viva explícitamente en otro lado. La memoria explícita no es redundancia; es la única forma de que el hecho sobreviva.
- **AP3 — Mezclar memoria e historial en una única estructura.** "Guardo todo en un blob para no tener dos tablas". La factura llega cuando necesitas truncar el historial sin tocar la memoria, o cuando un cambio de schema te obliga a migrar conversaciones antiguas.

**Las cuatro afirmaciones a interiorizar:** (1) historial y memoria son estructuras distintas con responsabilidades distintas; (2) la memoria sobrevive al truncado; (3) la memoria se materializa como estructura tipada (Pydantic) inyectada vía template y actualizada cada turno; (4) el olvido necesita políticas explícitas.

---

# PARTE 3 — Prompts adaptativos por perfil de usuario: el patrón "tier"

## 3.1 El antipatrón del prompt único

El `estimator` de la sesión 04 tiene un único system prompt: todos los usuarios reciben el mismo formato, detalle y vocabulario. Pero dos usuarios distintos hacen la misma petición sobre el mismo proyecto con necesidades opuestas:

- **Usuario A — desarrollador senior.** Quiere desglose por componentes técnicos (backend, frontend, infra, integraciones), horas por componente, riesgos técnicos, asunciones de stack, puntos de incertidumbre.
- **Usuario B — director comercial.** Quiere coste agregado, rango de duración, hitos visibles y nivel de confianza global. No le sirve "12h en configuración de PostgreSQL"; le sirve "Fase 1: Setup técnico — 2 semanas, riesgo bajo".

El sistema actual les devuelve a los dos **exactamente la misma respuesta**. La consecuencia: los usuarios empiezan a acompañar la transcripción con "dame el resumen ejecutivo solo" — y reaparece el patrón que combatimos en la sesión 04 (la calidad del output dependiendo del prompt del usuario). **La interfaz se convierte de nuevo en un chat encubierto.**

> **(para cualquiera)** Cuando un equipo senior se enfrenta por primera vez a "el sistema debe responder distinto según quién pregunte", el instinto es pensar en entrenar modelos distintos, fine-tuning o RLHF. Después de una semana investigando, alguien propone lo que iba a funcionar desde el principio: **una columna `tier` en la tabla de usuarios, un `if/elif` que elige la plantilla correcta, y dos schemas de salida distintos.** Esa propuesta tan poco glamorosa es la respuesta correcta.

## 3.2 Tier como dimensión de producto: tres capas

La solución correcta tiene **tres capas**, cada una en un sitio distinto:

```
Capa 1 — Persistencia (backend de negocio)
   users.tier (columna en BBDD)  ·  developer | pm | executive  ·  NO es autorización, es dimensión de producto
        │
Capa 2 — Propagación (canal autenticado)
   JWT con claim tier   ·   Header en red privada
        │
Capa 3 — Materialización (servicio IA)
   Template Jinja2: estimate_developer.j2 / estimate_pm.j2 / estimate_executive.j2
   Schema Pydantic:  DeveloperEstimate / PmEstimate / ExecutiveEstimate
```

**Capa 1 — el tier vive en la BBDD del backend de negocio.** Una columna `tier` con valores enumerados:

```ruby
# db/migrate/20250506_add_tier_to_users.rb
class AddTierToUsers < ActiveRecord::Migration[7.1]
  def change
    add_column :users, :tier, :string, null: false, default: "developer"
    add_index :users, :tier
  end
end

# app/models/user.rb
class User < ApplicationRecord
  TIERS = %w[developer pm executive].freeze
  validates :tier, inclusion: { in: TIERS }
end
```

> El tier **no es un rol de autorización** (qué *puede hacer* el usuario) — eso vive en otra columna. El tier es una **dimensión de producto**: define qué *experiencia* recibe. La separación importa porque un mismo rol de autorización puede mapear a tiers distintos: un developer técnico puede pedir el modo `executive` cuando prepara una presentación para el comité.

**Capa 2 — el tier viaja al servicio IA.** Dos maneras canónicas:
- **JWT firmado por el backend** que el servicio IA valida (correcto a medio plazo: añade defensa en profundidad y permite añadir claims —timezone, idioma, org_id— sin renegociar contratos):
  ```python
  import jwt
  from fastapi import Header, HTTPException

  def get_caller_context(authorization: str = Header(...)) -> CallerContext:
      token = authorization.removeprefix("Bearer ").strip()
      try:
          payload = jwt.decode(token, settings.ai_service_secret, algorithms=["HS256"])
      except jwt.PyJWTError:
          raise HTTPException(status_code=401, detail="Invalid token")
      return CallerContext(user_id=payload["sub"], tier=payload["tier"])
  ```
- **Header simple** en una red controlada (backend y servicio IA en la misma VPC; la confianza la garantiza la red, no la criptografía). Razonable mientras el sistema viva en una sola red privada.

**Capa 3 — el tier selecciona template y schema.** Aquí el tier deja de ser metadata y se convierte en **comportamiento**:

```python
# Output schemas — uno por tier
class DeveloperEstimate(BaseModel):
    components: list[ComponentEstimate]
    technical_risks: list[str]
    stack_assumptions: list[str]
    uncertainty_drivers: list[str]
    total_hours_range: tuple[int, int]

class PmEstimate(BaseModel):
    phases: list[PhaseEstimate]
    milestones: list[Milestone]
    team_composition: TeamComposition
    duration_weeks_range: tuple[int, int]
    blockers: list[str]

class ExecutiveEstimate(BaseModel):
    headline_cost_range: CostRange
    headline_duration_range: DurationRange
    confidence_level: Literal["low", "medium", "high"]
    top_three_risks: list[str]
    go_no_go_recommendation: str

# Resolution map
TIER_CONFIG = {
    "developer": {"template": "estimate_developer.j2", "schema": DeveloperEstimate},
    "pm":        {"template": "estimate_pm.j2",        "schema": PmEstimate},
    "executive": {"template": "estimate_executive.j2", "schema": ExecutiveEstimate},
}

def resolve_tier_config(tier: str) -> dict:
    config = TIER_CONFIG.get(tier)
    if config is None:
        raise ValueError(f"Unknown tier: {tier}")
    return config
```

Y el endpoint queda limpio:

```python
@app.post("/sessions/{session_id}/estimate")
async def estimate(session_id: str, transcript: str = Form(...),
                   attachments: list[UploadFile] = File(default=[]),
                   caller: CallerContext = Depends(get_caller_context)):
    config = resolve_tier_config(caller.tier)
    template = jinja_env.get_template(config["template"])
    output_schema = config["schema"]

    system_prompt = template.render(project_metadata=session.project_metadata, ...)
    response = await llm_client.responses.create(
        model="gpt-4o-mini",
        input=build_messages(system_prompt, transcript, attachments, session),
        response_format={"type": "json_schema", "json_schema": output_schema.model_json_schema()},
    )
    return output_schema.model_validate_json(response.output_text)
```

**Eso es todo el patrón.** La sofisticación está en haber tomado la decisión correcta, no en el código.

## 3.3 Diseñar los templates por tier

Los tres templates comparten estructura (rol, contexto CAG, transcripción, formato) y se diferencian en **instrucciones específicas**. Fragmento `developer`:

```jinja2
You are a senior software estimation expert producing estimates for the engineering team
that will execute the project. Your audience is technical: software engineers and tech leads
who need component-level breakdowns to plan their work and identify risks.

{% include "_project_metadata.j2" %}
{% include "_reference_estimates.j2" %}

When producing the estimate:
- Break down the work by technical component (backend, frontend, data layer, infrastructure, integrations).
- For each component, state hours estimate, technical risks, and stack assumptions.
- Surface uncertainty drivers explicitly: parts of scope where small decisions can disrupt the estimate by more than 20%.
- Speak to engineers as peers. Use technical vocabulary without translating it.

Return ONLY valid JSON matching the schema provided. Do not include narrative text outside the JSON.
```

Y `executive`:

```jinja2
You are a senior software estimation expert producing estimates for executive stakeholders
preparing strategic decisions or commercial proposals. Your audience is non-technical leadership:
heads of business, CTOs in oversight mode, sales directors. They need confident headline numbers
and risk awareness, not technical detail.

{% include "_project_metadata.j2" %}
{% include "_reference_estimates.j2" %}

When producing the estimate:
- Lead with a single cost range and a single duration range. No component-level breakdown.
- Provide an overall confidence level (low / medium / high) with one short justification.
- Surface only the top three risks that could materially affect the proposal.
- End with a go/no-go recommendation phrased as actionable executive guidance.
- Avoid technical jargon. If a stack decision matters, translate it into business terms.

Return ONLY valid JSON matching the schema provided.
```

Tres detalles:
- **Reutilización con `include`.** Los bloques compartidos (`_project_metadata.j2`, `_reference_estimates.j2`) viven en parciales que los tres templates importan. El día que cambia el CAG estático, lo cambias en un sitio.
- **Las instrucciones se diferencian, el formato no se mezcla.** El template `developer` no dice "muestra más detalle"; dice *qué dimensiones* componen ese detalle. El `executive` no dice "sé conciso"; especifica *qué piezas* componen una salida ejecutiva. El modelo trabaja mucho mejor con instrucciones específicas.
- **El schema actúa como segundo guardrail.** Aunque el template indique qué devolver, `response_format` con `json_schema` lo *fuerza*. Si el LLM olvida una sección, la validación falla y el sistema lo detecta antes de que el usuario reciba algo defectuoso.

## 3.4 Cómo gestionar la evolución de tiers

¿Qué pasa cuando el producto necesita un cuarto tier? La respuesta **no** es añadir entradas a `TIER_CONFIG` indefinidamente. Tres heurísticas:
- **H1 — Tres es el número adecuado para arrancar.** Cubre la mayoría de casos sin caer en fragmentación. Si necesitas más, lo descubrirás por evidencia (usuarios pidiendo lo que ningún tier sirve), no por anticipación.
- **H2 — Tier compuesto = señal de tier mal definido.** Si necesitas "executive con un poco de developer", probablemente al `executive` le falta una sección de "appendix técnico". Casi siempre es más barato **refinar** un tier que multiplicarlos.
- **H3 — Nuevos tiers exigen evaluación, no intuición.** Cada tier nuevo es un template + un schema + casos de prueba. Sin un golden dataset que valide que produce respuestas distintas y de calidad para sus usuarios reales, estás añadiendo complejidad sin valor verificable.

## 3.5 El antipatrón paralelo: el tier que solo cambia el tono

Hay una forma que parece bien, funciona en la demo y se rompe en producción: mantener **un único schema y un único template** y limitarse a añadir "responde en {tono} según el tier":

```jinja2
{% if tier == "executive" %}Respond in an executive tone, focused on strategic implications.
{% elif tier == "pm" %}Respond in a project management tone, focused on phases and risks.
{% else %}Respond in a technical tone with implementation detail.{% endif %}
```

Funciona porque los modelos modernos adaptan el tono. **Falla porque la _estructura_ de la respuesta es la misma para todos**, y la estructura es donde vive el valor de adaptación. El usuario ejecutivo sigue recibiendo una respuesta organizada por componentes técnicos, solo que con palabras menos técnicas.

**La regla operativa: adaptar un sistema CAG a perfiles distintos significa adaptar la _estructura de salida_, no solo el tono.** Si el tier no cambia el schema Pydantic, lo más probable es que estés haciendo lock-in cosmético, no diseño de producto.

## 3.6 Cuando un tier merece su propia pipeline (el modo deep research)

Hasta aquí los tres tiers comparten la **misma pipeline**: una sola llamada al LLM con template y schema. Hay un patrón superior que marca el techo del enfoque: **un tier puede activar una pipeline completamente distinta.** El ejemplo paradigmático es el *Deep Research* de OpenAI: invoca un modelo distinto (`o3-deep-research`), habilita web search por defecto, opera en modo `background` con tiempos de minutos, y devuelve un informe largo con citas.

```python
TIER_CONFIG = {
    "developer": {"pipeline": "single_call", "template": "estimate_developer.j2", "schema": DeveloperEstimate, "model": "gpt-4o-mini"},
    "pm":        {"pipeline": "single_call", "template": "estimate_pm.j2",        "schema": PmEstimate,        "model": "gpt-4o-mini"},
    "executive": {"pipeline": "single_call", "template": "estimate_executive.j2", "schema": ExecutiveEstimate, "model": "gpt-4o-mini"},
    "research":  {"pipeline": "deep_research", "template": "estimate_research.j2", "schema": ResearchEstimate,
                  "model": "o3-deep-research", "tools": ["web_search", "code_interpreter"],
                  "background": True, "estimated_latency_seconds": 600, "estimated_cost_per_call_eur": 5.00},
}

PIPELINE_HANDLERS = {
    "single_call": run_single_call_pipeline,
    "deep_research": run_deep_research_pipeline,
}

async def estimate(...):
    config = resolve_tier_config(caller.tier)
    handler = PIPELINE_HANDLERS[config["pipeline"]]
    return await handler(config, session, transcript, attachments)
```

El tier `research` cuesta **minutos** (no segundos) y **euros** (no céntimos); la interfaz lo refleja: avisa del tiempo de espera, permite cerrar la pestaña y recibir el resultado por email, y ofrece descargarlo en PDF. **La lección: el patrón tier escala desde "mismo motor, distinta presentación" hasta "motor completamente distinto".** Conocer ese rango cambia cómo diseñas la abstracción desde el principio.

## 3.7 Anti-patrones frecuentes

- **AP1 — El tier vive en el frontend.** "Mi cliente envía un parámetro `tier` en el body y el servicio IA lo respeta". La forma más rápida de implementar y la más rápida de explotar: cualquiera envía `tier=executive` y accede al modo más caro. **El tier debe vivir en la BBDD del backend y propagarse por un canal que el cliente no pueda manipular.**
- **AP2 — Un solo schema, branching de campos.** "Un único `EstimateOutput` con todos los campos posibles, y el modelo rellena los que correspondan". El schema deja de ser un contrato: el modelo a veces rellena campos que no debería, el cliente no sabe qué esperar, los validadores no pueden trabajar. **Schemas separados por tier = más código pero contrato nítido.**
- **AP3 — Los templates por tier divergen sin disciplina.** Empiezas con tres templates compartiendo el 80%; tres meses después cada uno evolucionó por su cuenta y los bloques compartidos están duplicados. La disciplina de parciales con `include` no es opcional cuando los templates se multiplican.

---

# PARTE 4 — Testing y evaluación de sistemas con LLMs

## 4.1 Por qué `assert response == "expected"` no funciona

Todo desarrollador senior ha interiorizado: *software sin tests no es producción*. Pero el test unitario clásico choca con una pared:

```python
def test_estimate_basic_project():
    result = estimator.estimate("Build a simple landing page in HTML and CSS")
    assert result.total_hours == 16
```

Este test **falla el 30% de las veces aunque el sistema funcione perfectamente.** La misma transcripción puede producir 14, 16, 18, o "rango 10–22 con confianza media". Las tres son correctas. El test es **inadecuado para el sistema que evalúa**, porque los criterios de testing tradicionales no aplican a outputs probabilísticos.

La igualdad estricta produce dos clases de error:
- **Falsos negativos masivos.** El test falla porque el modelo dijo "16 horas" cuando esperabas "16h". El sistema funciona, la suite está roja, y alguien acaba añadiendo `if "16" in result` y la suite "pasa por casualidad". La señal se ha perdido.
- **Falsos positivos silenciosos.** El test pasa porque comparas que el resultado es un string de longitud > 0. El sistema en producción devuelve "Lo siento, no puedo ayudarte" para cualquier input y los tests siguen verdes.

**La conclusión operativa: en sistemas con LLM, el test no comprueba _igualdad_ sino _propiedades_.** Una respuesta es válida si cumple un conjunto de propiedades verificables. Para el `estimator`: el output es JSON válido contra el schema, las horas caen en un rango razonable, la respuesta menciona los componentes de la transcripción, no contradice `project_metadata`, y mantiene consistencia entre invocaciones.

## 4.2 Las tres familias de tests (la pirámide)

```
                    ╱╲  Calidad subjetiva (LLM-as-judge, DeepEval GEval)
                   ╱  ╲     pocos tests · caro, lento, valioso
                  ╱────╲
                 ╱      ╲  Determinismo soft (consistencia entre runs, varianza acotada)
                ╱        ╲    algunos tests · medio
               ╱──────────╲
              ╱            ╲ Determinismo hard (schema válido, rangos plausibles,
             ╱              ╲   campos obligatorios, SIN llamadas extra al LLM)
            ╱────────────────╲   muchos tests · barato, rápido
```

**Familia 1 — Tests deterministas _hard_.** La propiedad verificada **no depende del modelo**. La respuesta se trata como input opaco y la verificación es estructural/numérica, sin otra llamada al LLM. Baratos, rápidos, **la primera capa siempre**:

```python
import pytest
from estimator.client import estimate
from estimator.schemas import DeveloperEstimate

@pytest.mark.asyncio
async def test_estimate_returns_valid_schema():
    result = await estimate(tier="developer", transcript="Build a simple landing page with contact form.")
    assert isinstance(result, DeveloperEstimate)

@pytest.mark.asyncio
async def test_estimate_hours_in_reasonable_range():
    result = await estimate(tier="developer", transcript="Build a simple landing page with contact form.")
    low, high = result.total_hours_range
    assert 0 < low <= high <= 200, f"Unreasonable hours range: {low}-{high}"

@pytest.mark.asyncio
async def test_estimate_components_present():
    result = await estimate(tier="developer", transcript="Build a simple landing page with contact form.")
    assert len(result.components) >= 1
    assert all(component.name.strip() for component in result.components)
```
> Si el equipo no tiene cobertura mínima en esta familia, **cualquier discusión sobre LLM-as-judge es prematura.**

**Familia 2 — Tests deterministas _soft_.** Introducen **propiedades estadísticas**: ejecutas el sistema N veces sobre el mismo input y verificas que la *distribución* tiene la forma esperada. El caso paradigmático es la **consistencia**:

```python
import statistics

@pytest.mark.asyncio
async def test_estimate_consistency():
    transcript = "Build a simple landing page with contact form."
    n_runs = 5
    results = [await estimate(tier="developer", transcript=transcript) for _ in range(n_runs)]
    midpoints = [(r.total_hours_range[0] + r.total_hours_range[1]) / 2 for r in results]
    mean = statistics.mean(midpoints)
    coefficient_of_variation = statistics.stdev(midpoints) / mean
    # We accept up to 25% relative variability across runs
    assert coefficient_of_variation < 0.25, f"Inconsistent estimates: CV={coefficient_of_variation}, midpoints={midpoints}"
```
Más caros (5 llamadas por test) y más lentos. Detectan una clase de fallo que ningún test hard captura: que el sistema responda *correctamente* pero con varianza inaceptable → usuarios perdiendo confianza. Córrelos con menos frecuencia (solo en CI antes de merge, no en cada commit local).

**Familia 3 — Tests de calidad subjetiva (LLM-as-judge).** La propiedad es genuinamente subjetiva (¿la justificación es coherente con el alcance? ¿menciona los riesgos relevantes?). Solo un juez —humano o LLM— puede valorarlo. El patrón canónico es **LLM-as-judge**: una segunda llamada con prompt de evaluación que emite un veredicto, en dos modos: **pointwise** (puntúa 0–1) o **pairwise** (compara dos respuestas). DeepEval lo encapsula en su métrica **`GEval`**:

```python
from deepeval import assert_test
from deepeval.test_case import LLMTestCase, SingleTurnParams
from deepeval.metrics import GEval

def test_estimate_justification_coherence():
    transcript = "Build a simple landing page with contact form."
    estimate_result = run_estimate_sync(tier="developer", transcript=transcript)

    coherence = GEval(
        name="JustificationCoherence",
        criteria=(
            "Determine whether the technical risks listed in the actual output "
            "are coherent with the project scope described in the input. "
            "A coherent justification mentions risks that are plausible for the "
            "scope and avoids irrelevant risks."
        ),
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        threshold=0.7,
    )
    test_case = LLMTestCase(input=transcript, actual_output=estimate_result.model_dump_json())
    assert_test(test_case, [coherence])
```
Tres precauciones: (1) **el juez también es un LLM y también se equivoca** — puede tener sesgos sistemáticos (preferir respuestas largas); calíbralo contra veredictos humanos. (2) **El umbral importa más que la métrica** — 0.7 no es universal; empieza en 0.5 y ajusta. (3) **No abuses** — cada test es una llamada extra; resérvalo para propiedades que realmente no se puedan capturar de otra forma. *Si una propiedad se puede testear con un regex, no la testees con un juez.*

## 4.3 El golden dataset

Usar una única transcripción de prueba basta para entender la mecánica pero es insuficiente para evaluar en serio. El **golden dataset** es un conjunto **curado** de casos representativos, cada uno **anotado con el comportamiento esperado**. Para el `estimator`, 5–15 transcripciones que cubran el espectro real:

- Un proyecto simple bien acotado (landing page, formulario).
- Un proyecto medio con múltiples componentes (panel admin con auth y reportes).
- Un proyecto grande con dependencias externas (3 APIs de pago, cola asíncrona).
- Un caso ambiguo donde la transcripción no especifica detalles críticos.
- Un caso límite con contradicciones internas.
- Un caso multilingüe si el sistema lo soporta.

Cada caso lleva metadata (categoría, horas que estimaría un experto, riesgos clave, componentes esperados). **Esa metadata es lo que convierte el dataset en _golden_: no es una lista de inputs, es una lista de inputs _con sus criterios de éxito_.**

```python
from deepeval.dataset import EvaluationDataset, Golden

golden_dataset = EvaluationDataset(
    goldens=[
        Golden(
            input="Build a simple landing page with contact form.",
            expected_output=None,  # No exact answer expected
            additional_metadata={
                "category": "small_project",
                "expected_hours_range": (16, 40),
                "expected_components": ["frontend", "form_handling"],
            },
        ),
        Golden(
            input="We need an internal admin dashboard with user management, role-based permissions, audit log, and weekly email reports.",
            additional_metadata={
                "category": "medium_project",
                "expected_hours_range": (200, 400),
                "expected_components": ["backend", "frontend", "auth", "reporting"],
            },
        ),
        # ... more goldens
    ]
)
```

Construirlo es trabajo (un caso bien anotado puede costar 1 h a un experto). **Es una inversión, no un coste:** se amortiza en la primera regresión que evita. Heurísticas: representa la distribución real de inputs (no inventes casos exóticos), incluye al menos un caso límite por categoría, y **revísalo cada tres meses**.

## 4.4 Anatomía de una suite con DeepEval + pytest

**DeepEval** encadena las tres familias sobre el golden dataset. Elección: nativo pytest, sin infra externa, métricas listas (`AnswerRelevancyMetric`, `FaithfulnessMetric`, `GEval`):

```python
import pytest, statistics
from deepeval import assert_test
from deepeval.test_case import LLMTestCase, SingleTurnParams
from deepeval.metrics import GEval
from estimator.client import estimate_sync
from estimator.schemas import DeveloperEstimate
from tests.fixtures import golden_dataset

# Family 1 — Hard determinism
@pytest.mark.parametrize("golden", golden_dataset.goldens)
def test_schema_validity(golden):
    result = estimate_sync(tier="developer", transcript=golden.input)
    assert isinstance(result, DeveloperEstimate)

@pytest.mark.parametrize("golden", golden_dataset.goldens)
def test_hours_within_expected_range(golden):
    result = estimate_sync(tier="developer", transcript=golden.input)
    low, high = result.total_hours_range
    expected_low, expected_high = golden.additional_metadata["expected_hours_range"]
    # Allow 50% overshoot in either direction — generous on a first pass
    assert low >= expected_low * 0.5
    assert high <= expected_high * 1.5

# Family 2 — Soft determinism
@pytest.mark.slow
@pytest.mark.parametrize("golden", golden_dataset.goldens[:3])  # only a sample
def test_consistency_across_runs(golden):
    n_runs = 3
    results = [estimate_sync(tier="developer", transcript=golden.input) for _ in range(n_runs)]
    midpoints = [(r.total_hours_range[0] + r.total_hours_range[1]) / 2 for r in results]
    cv = statistics.stdev(midpoints) / statistics.mean(midpoints)
    assert cv < 0.25

# Family 3 — Subjective quality (LLM-as-judge)
coherence_metric = GEval(
    name="ScopeCoherence",
    criteria=(
        "Evaluate whether the components and risks in the actual output match "
        "the scope of the project described in the input. "
        "Penalize outputs that mention components or risks not implied by the scope."
    ),
    evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
    threshold=0.7,
)

@pytest.mark.slow
@pytest.mark.parametrize("golden", golden_dataset.goldens)
def test_scope_coherence(golden):
    result = estimate_sync(tier="developer", transcript=golden.input)
    test_case = LLMTestCase(input=golden.input, actual_output=result.model_dump_json())
    assert_test(test_case, [coherence_metric])
```

Tres detalles operativos:
- **Marcado con `@pytest.mark.slow`.** Permite correr solo la suite rápida en desarrollo (`pytest -m "not slow"`) y reservar la completa para CI. Sin esta separación, el equipo deja de correr la suite en local.
- **Parametrización con el golden dataset.** Cada test se ejecuta una vez por golden → tres tests se convierten en treinta o cuarenta casos efectivos sin duplicar código. Pytest reporta cada combinación por separado, así sabes exactamente qué caso se rompió.
- **Tolerancias generosas en la primera pasada.** Aceptar 50% de desviación es deliberado: en la primera pasada quieres detectar fallos catastróficos (una landing page estimada en 800 h), no microajustes. Cuando el sistema madure, ajustas hacia abajo.

## 4.5 Anti-patrones y lo que no cubre todavía

**Anti-patrones:**
- **AP1 — Testar la respuesta del modelo en lugar de las propiedades de tu sistema.** "Respondió 16 en lugar de 18, ajusto el test". El test pasa a memorizar salidas concretas; cuando OpenAI actualiza el modelo (sin avisar), todo rompe y el equipo cree que hay un bug inexistente. Testa propiedades, no salidas específicas.
- **AP2 — Suite de evals que es solo familia 3.** Lentísima, carísima, y todos los tests dependen del mismo punto de fallo (el LLM juez). Una suite sana es **piramidal**. *Si el cuerpo de la suite está en la cima, algo está mal.*
- **AP3 — Construir el golden dataset una vez y olvidarlo.** Lo representativo en febrero deja de serlo en agosto cuando los usuarios envían un tipo nuevo de transcripción. Consecuencia: tests verdes y producción fallando. Revísalo cada trimestre.

**Lo que esta primera exposición NO cubre** (se trata en la sesión 15, LLMOps y producción):
- **Métricas especializadas para RAG** (faithfulness, contextual precision, answer relevancy). Frameworks como **RAGAS**.
- **Tests de regresión continuos en CI/CD** (bloquear merges si el score cae bajo un umbral).
- **Monitoring en producción** (online evals sobre tráfico real). Plataformas como **Langfuse**, **Confident AI** o **Logfire**.
- **Red teaming automatizado** (inputs adversariales). **Promptfoo** es la referencia.
- **Datasets sintéticos** (generar casos con LLM a partir de un seed pequeño).

> Esa madurez se construye **progresivamente desde la base de aquí, no en sustitución de ella.** Las cuatro afirmaciones: (1) el test unitario clásico no aplica a outputs de LLM — testa propiedades; (2) tres familias con costes y propósitos distintos, en proporción piramidal; (3) el golden dataset es la base de todo lo demás; (4) DeepEval + pytest cubre la base mínima sin infra externa.

---

# PARTE 5 — Actor-Critic-Boss: la composición de roles que eleva la calidad

## 5.1 Por qué un mejor prompt no es la solución

A estas alturas el `estimator` es un sistema serio: recibe adjuntos, mantiene memoria separada, adapta su salida al perfil, tiene evals. Y aun así, mirando de cerca las salidas, hay un **techo de calidad que no se rompe solo refinando prompts**: aritméticas internas que no cuadran, riesgos importantes que no se mencionan, componentes que aparecen en la justificación pero no en el desglose de horas, casos límite donde el modelo elige una de dos respuestas sin verificar si era la correcta.

El punto donde el prompt deja de funcionar es donde el problema **no es de instrucción, sino de verificación.** Cuando un humano produce una estimación importante, el flujo natural no es "pienso una respuesta y la entrego". Es *"pienso una respuesta, la reviso, encuentro un error, lo corrijo, vuelvo a revisar"*. Esa segunda pasada es **estructuralmente distinta** de la generación: usa criterios explícitos, va a contracorriente del razonamiento original, y descubre cosas que el generador no veía porque estaba comprometido con su propia narrativa.

Un único LLM en una sola llamada hace ambas cosas a la vez y resulta que los modelos no son buenos en autocrítica genuina. Madaan et al. mostraron en **Self-Refine (2023)** que separar generación de feedback en dos llamadas distintas mejoraba la calidad un **20% absoluto** de media sobre siete tareas, sin entrenamiento adicional. **Mezclar generación y verificación en una misma llamada degrada ambas funciones.**

## 5.2 Composición de roles: Actor, Critic, Boss

El patrón separa el trabajo en **tres roles**, cada uno una llamada al LLM con su propio prompt y su propio criterio de éxito:

```
Entrada (transcript + metadata)
        │
        ▼
   ┌─────────┐
   │  ACTOR  │  genera estimación inicial
   └─────────┘
        │  candidate_estimate
        ▼
   ┌─────────┐
   │  CRITIC │  evalúa contra criterios  ◀──┐
   └─────────┘                              │ iterar máx. 2-3
        │  feedback estructurado            │
        ▼                                   │
   ┌─────────┐                              │
   │   BOSS  │  aceptar / iterar / sintetizar ─┘
   └─────────┘
        │
        ▼
   Salida (final_estimate)
```

- **Actor.** Genera la estimación inicial a partir de transcripción, adjuntos y `project_metadata`. **Es la llamada que el `estimator` ya hace hoy; no cambia** (template Jinja2 por tier, schema Pydantic, contexto CAG). La diferencia: su salida deja de ser la respuesta final y pasa a ser un **candidato**.
- **Critic.** Recibe el output del actor y lo evalúa contra criterios explícitos: ¿está completo? ¿la aritmética cuadra? ¿los riesgos son coherentes con el alcance? ¿hay contradicciones con `project_metadata`? ¿faltan componentes que la transcripción menciona? **El crítico NO genera una nueva estimación: produce _feedback estructurado_** sobre la que recibió.
- **Boss.** Recibe estimación + feedback y **decide**: si no hay problemas materiales, acepta tal cual. Si hay problemas corregibles, devuelve al actor con instrucciones específicas para una nueva iteración. Si el feedback es complejo, sintetiza la versión final integrando ambos. Y **crucialmente, limita el número de iteraciones** para acotar coste y latencia.

## 5.3 Anclaje en la literatura

Aunque el nombre "Actor-Critic-Boss" es del programa, los tres roles tienen anclaje sólido. Conocerlo da autoridad para defender el patrón y abre la puerta a la investigación:

| Rol | Equivalente en la literatura | Fuente principal |
|---|---|---|
| **Actor** | Generator / Optimizer | Anthropic, *Building Effective Agents* (2024); Madaan et al., *Self-Refine* (2023); Estornell et al., *ACC-Collab* (2024) |
| **Critic** | Evaluator / Critic / Self-Verifier | Anthropic, *Building Effective Agents*; Madaan et al., *Self-Refine*; Shinn et al., *Reflexion* (2023) |
| **Boss** | Orchestrator / Supervisor | Anthropic, *Building Effective Agents* (orchestrator-workers); *LLaMAC* (2023) |

El ensayo *Building Effective Agents* de Anthropic formaliza dos workflows que son la base directa:
- **Evaluator-Optimizer:** un LLM genera, otro evalúa, se itera → origen de `actor + critic`.
- **Orchestrator-Workers:** un LLM central descompone, delega y sintetiza → origen de `boss`.

Lo que **añade Actor-Critic-Boss** sobre versiones más simples (Self-Refine puro) es la **separación explícita entre evaluación y decisión**.

## 5.4 Por qué tres roles y no dos

```
  Dos roles (Self-Refine puro)          Tres roles (Actor-Critic-Boss)
  ┌──────────────┐                      ┌──────────────┐
  │ Actor: genera│                      │ Actor: genera│
  └──────────────┘                      └──────────────┘
         │                                     │
  ┌──────────────────┐                  ┌──────────────┐
  │ Critic + decisor │                  │ Critic: solo │
  │ evalúa Y decide  │                  │ evalúa       │
  └──────────────────┘                  └──────────────┘
   modo de fallo:                              │
   • Bucle infinito (insatisfacción     ┌──────────────┐
     crónica)                           │ Boss: solo   │
   • Aceptación temprana (sesgo de      │ decide       │
     confirmación)                      └──────────────┘
                                        resultado: Convergencia acotada y predecible
```

Si el crítico **también decide** qué hacer con su propio feedback, aparecen dos modos de fallo reportados en Self-Refine puro:
- **Bucles infinitos por insatisfacción crónica.** Un crítico bien calibrado casi siempre encuentra algo que mejorar. Sin árbitro externo, el sistema itera con mejoras marginales, agotando presupuesto y latencia sin convergencia. El problema no es del crítico (hace su trabajo); es que **evaluar y decidir cuándo parar son funciones diferentes.**
- **Sesgo de confirmación temprana.** El opuesto: el crítico se vuelve cómplice del actor y acepta la primera respuesta. En modelos donde el mismo LLM actúa de crítico y de actor, el sesgo es fuerte porque el modelo tiende a defender lo que acaba de producir.

**Separar evaluación de decisión rompe ambos.** El crítico se concentra en feedback de calidad. El boss, con prompt y criterios distintos —centrados en *governance* del proceso, no en calidad técnica—, decide cuándo lo bueno es suficientemente bueno. Tiene un paralelo directo en equipos humanos: el ingeniero hace el trabajo, el revisor identifica problemas, el tech lead decide cuáles bloquean el merge. **La especialización funciona.**

## 5.5 Cuándo el patrón compensa y cuándo es overkill

Triplica las llamadas al LLM (mínimo) y multiplica la latencia. **Compensa cuando se cumplen al menos dos** de estas condiciones:
- **El coste del error es alto.** Una estimación que será base de un contrato comercial; una recomendación médica; un análisis para una decisión de inversión. Una respuesta defectuosa cuesta más que la latencia.
- **Existen criterios de evaluación claros.** El crítico necesita instrucciones específicas. Si los criterios son "que esté bien", el patrón degenera. Para el `estimator` son claros: aritmética interna, completitud de componentes, coherencia con la transcripción.
- **La latencia adicional es tolerable.** En un loop de chat con expectativa de respuesta inmediata, multiplicar por tres rompe la experiencia. En un informe que el usuario recibe cuando esté listo, los segundos extra son aceptables.

**Es overkill cuando:** la tarea es simple y difícilmente errónea ("traduce este texto"); ya hay tests hard que cubren los modos de fallo importantes; el coste por petición ya es crítico para el negocio; o los criterios son tan vagos que el crítico no añade información.

**Regla operativa: aplica el patrón solo a los _caminos críticos_ del producto, no a todas las llamadas al LLM.** Para el `estimator`: al flujo de generación de estimación final, no a la extracción de `project_metadata` ni a respuestas auxiliares.

## 5.6 Anti-patrones frecuentes

- **AP1 — Tres llamadas con prácticamente el mismo prompt.** Si actor, crítico y boss usan templates parecidos, pagas tres veces sin ganancia: el crítico hace lo mismo que el actor y el boss repite al crítico. **Cada rol necesita un prompt estructuralmente distinto:** el actor optimiza por generación, el crítico por detección de fallos, el boss por gobernanza del proceso.
- **AP2 — El crítico devuelve texto libre.** El boss recibe un párrafo y tiene que interpretarlo; la interpretación falla y el sistema se vuelve menos predecible que el monolítico de partida. **El feedback debe ser estructurado:** lista de issues con categoría (`arithmetic_error`, `missing_component`, `inconsistency_with_metadata`…), severidad (`critical`, `major`, `minor`) y referencia al campo afectado. La disciplina de schemas Pydantic aplica directamente.
- **AP3 — Iteraciones sin límite.** "El boss para cuando el crítico no encuentre más problemas". En la práctica el crítico siempre encuentra algo. **El boss siempre opera con un presupuesto máximo de iteraciones (típicamente 2 o 3);** cuando se agota, sintetiza la mejor respuesta disponible y la entrega aunque no sea perfecta. **Producción se prefiere a perfección.**

> Lo importante de esta pieza no es la implementación —relativamente directa— sino haber interiorizado **por qué** la separación de roles eleva la calidad. Cuando ese *por qué* está claro, el *cómo* se construye solo.

---

## Cómo conecta con nuestro ejercicio y con el directo

Las cinco partes no son temas sueltos: son **cinco capas que se montan sobre el mismo `estimator`** y, juntas, lo convierten de prototipo en producto. El orden no es casual:

1. **Contexto dinámico (PARTE 1)** amplía *qué información* entra en cada decisión, manteniendo el aislamiento entre capas (servicio IA ↔ backend de negocio por contrato HTTP). Es la antesala conceptual de RAG (módulo 3): la extracción de texto de adjuntos es ya la primera pieza del pipeline de chunking.
2. **Memoria vs historial (PARTE 2)** da al sistema continuidad multi-turno sin reventar coste ni latencia. El `ProjectMetadata` tipado es la pieza que sobrevive al truncado y la que se inyecta en *todos* los templates de las partes siguientes.
3. **Patrón tier (PARTE 3)** adapta la *estructura de salida* al consumidor. Reutiliza la memoria (la inyecta en cada template por tier) y la disciplina de schemas de la sesión 04.
4. **Testing/evals (PARTE 4)** es lo que permite tocar las tres capas anteriores **sin miedo**. Sin evals, cada cambio de prompt es a ciegas; con evals, detectas regresiones antes que los usuarios.
5. **Actor-Critic-Boss (PARTE 5)** sube el techo de calidad del camino crítico (la estimación final), apoyándose en los criterios de evaluación que la PARTE 4 ya te obligó a explicitar.

**Hilo transversal — la misma regla operativa en las cinco:** *no añadas potencia (contexto, memoria, tiers, juez LLM, roles) por defecto. Añádela cuando tengas evidencia de que el sistema la necesita, mide siempre el coste en tokens y latencia, y mantén el aislamiento entre capas.* La sofisticación vive en la arquitectura, no en el modelo.

**Divergencias de nuestro proyecto** (alineado al repo del profesor post-sesión-5 pero con nuestras decisiones propias): mantenemos Postgres único + telemetría propia + frontend Angular; cuando estas partes aterricen en código, el `ProjectMetadata`, el `TIER_CONFIG` y el flujo Actor-Critic-Boss se implementan sobre ese stack. Ver [session-08-theory.md](../session-08-datadrivenai-bbdd-vectoriales/session-08-theory-datadrivenai-bbdd-vectoriales.md) para la capa de persistencia vectorial (pgvector) que continúa esta línea en el módulo de RAG.

---

### Chuleta de una página (lo imprescindible)

**PARTE 1 — Contexto dinámico.** Tres reglas: es *input* no programa (cuidado con prompt injection), tiene coste por petición, añade latencia. Tres mecanismos: **adjuntos** (multimodal directo vs extracción local; extracción = terreno para RAG), **búsqueda web** (nativa / Tavily-Exa / SERP; solo si es sensible al tiempo), **BBDD del negocio** (function calling vía HTTP, NUNCA acceso directo). Los orquesta el *agentic loop*; controla budget de tokens + trazabilidad.

**PARTE 2 — Memoria vs historial.** **Historial** = array de mensajes bruto (qué se dijo). **Memoria** = hechos destilados (qué sabemos). La memoria sobrevive al truncado → materialízala como `ProjectMetadata` (Pydantic), inyéctala en el system prompt (renderizado condicional + "treat as established facts"), actualízala cada turno (heurística barata vs LLM extractor robusto). Olvido = 3 políticas (revisión usuario / TTL sesión / reset). Ventana deslizante `MAX_TURNS=6` + memoria separada = arquitectura razonable.

**PARTE 3 — Patrón tier.** Adaptar a perfiles = **desarrollo web normal**, no IA avanzada. Tres capas: tier en **BBDD del backend** (dimensión de producto, no autorización) → propagado por **canal autenticado** (JWT/header, NUNCA param del cliente) → materializa **template + schema por tier** en el servicio IA. Adaptar = cambiar la **estructura de salida** (schema Pydantic distinto), no solo el tono. Escala hasta "pipeline completamente distinta" (deep research).

**PARTE 4 — Testing/evals.** `assert == expected` NO funciona; testa **propiedades**. Pirámide de **tres familias**: hard (estructural, barato, base) → soft (estadístico, consistencia/varianza, medio) → subjetivo (LLM-as-judge / DeepEval `GEval`, caro, cima). Base de todo: **golden dataset** (5-15 casos curados + criterios de éxito; inversión, no coste; revisión trimestral). Herramienta: DeepEval + pytest, `@pytest.mark.slow` + parametrización. Testa propiedades del sistema, no salidas del modelo.

**PARTE 5 — Actor-Critic-Boss.** Hay un techo que no rompe el prompt: el problema es de **verificación**, no de instrucción (Self-Refine: +20% separando generación de feedback). **Tres roles, no dos:** Actor genera, Critic **solo** evalúa (feedback estructurado), Boss **solo** decide (acepta/itera/sintetiza, con límite 2-3 iteraciones). Separar evaluación de decisión rompe bucles infinitos + sesgo de confirmación. Anclado en *Building Effective Agents* (evaluator-optimizer + orchestrator-workers). Compensa si: coste del error alto + criterios claros + latencia tolerable. Solo en caminos críticos.
