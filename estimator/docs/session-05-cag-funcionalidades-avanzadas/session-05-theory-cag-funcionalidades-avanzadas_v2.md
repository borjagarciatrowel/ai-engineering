# Sesión 05 — Contexto dinámico, memoria, tiers, evaluación y Actor-Critic-Boss (versión clara)

> Versión simplificada del resumen de los 5 artículos de la Sesión 05 (AI Engineering 2026, Antonio Pérez / LIDR). Cada PARTE = un artículo.
> Misma información, menos paja. Cada término técnico se explica en una frase.
> **Hilo conductor:** el **`estimator`**, un servicio de IA que produce estimaciones de software a partir de transcripciones de reuniones — y las 5 piezas que lo convierten de prototipo en producto.

---

## Glosario base (léelo una vez y vuelve cuando haga falta)

| Término | Qué es, en una frase |
|---|---|
| **CAG** (Context-Augmented Generation) | Meter contexto en el prompt del LLM directamente, sin un buscador semántico detrás (eso ya es RAG). |
| **LLM** | El modelo de lenguaje que genera la respuesta. |
| **Contexto estático** | Lo que el equipo escribió de antemano y no cambia entre peticiones (templates, ejemplos en el prompt). |
| **Contexto dinámico** | Lo que el sistema va a buscar en el momento porque depende de lo que el usuario acaba de pedir (un PDF, precios de hoy, datos de la BBDD). |
| **Tokens** | Las unidades en que el LLM cobra y mide texto. Más contexto = más tokens = más dinero. |
| **Latencia** | Cuánto tarda en responder. El coste que más nota el usuario. |
| **Prompt injection** | Ataque en el que un texto externo lleva instrucciones disfrazadas que el LLM obedece como si fueran tuyas. |
| **Function calling / tool** | Darle al LLM una "herramienta" que puede invocar (buscar en web, llamar a una API); el LLM decide cuándo usarla. |
| **Agentic loop** | El ciclo razonar → invocar tool → recibir resultado → razonar de nuevo, hasta dar la respuesta final. |
| **Schema (Pydantic)** | Un contrato tipado que define qué campos debe tener una salida; sirve para validarla. |
| **Template Jinja2** | Plantilla de texto con huecos (`{{ }}`) y condicionales para construir el prompt. |
| **Tier** | El perfil del usuario (developer / pm / executive) que decide qué *experiencia* recibe, no qué *puede hacer*. |
| **Golden dataset** | Conjunto curado de casos de prueba, cada uno con su criterio de éxito anotado a mano. |

> **El hilo común de las 5 partes:** la sofisticación de un sistema de IA bien hecho casi nunca vive en el modelo; vive en la **arquitectura que lo rodea.** Y la regla operativa es siempre la misma: *no añadas potencia por defecto; añádela cuando tengas evidencia de que el sistema la necesita, y mide siempre el coste en tokens y latencia.*

---

## La idea en una página

Hasta la Sesión 04 el `estimator` era una máquina de un botón: metes una transcripción, monta un prompt fijo, el LLM devuelve una estimación. Todo su "conocimiento" estaba escrito a mano en el código. Funciona en el laboratorio, se rompe en el mundo real. La Sesión 05 añade las 5 piezas que faltan:

| # | Pieza | Qué resuelve |
|---|-------|--------------|
| 1 | **Contexto dinámico** | Traer info de fuera en tiempo real (PDF, precios cloud, histórico de la empresa) — y *cuándo* activar cada fuente, porque cada una cuesta dinero y latencia. |
| 2 | **Memoria vs historial** | Recordar de qué va la conversación sin reenviarlo todo cada turno. Distinguir el **historial** (lo que se dijo) de la **memoria** (los hechos destilados). |
| 3 | **Patrón tier** | Responder distinto según quién pregunta (un dev y un comercial necesitan formatos opuestos). No es IA avanzada: es una columna en BBDD y un selector de plantilla. |
| 4 | **Testing / evaluación** | Saber si el sistema funciona, cuando `assert == "16h"` no sirve (el mismo input da 14, 16 o "10-22"). Testar **propiedades**, no igualdad. |
| 5 | **Actor-Critic-Boss** | Subir el techo de calidad: tres roles (uno **genera**, otro **critica**, otro **decide**) que imitan cómo un humano revisa su trabajo antes de entregarlo. |

---

# PARTE 1 — Contexto dinámico desde fuentes externas

## 1.1 Estático vs dinámico

Hasta ahora todo el contexto era **estático**: vivía en código (templates, ejemplos hardcoded) o en parámetros del formulario. Predecible, versionable, testeable.

El **dinámico** lo obtiene el sistema **en tiempo de ejecución**, según la petición concreta. No vive en código; vive en sistemas externos: archivos del usuario, la web, una BBDD, un sistema de tickets.

## 1.2 Las tres reglas del contexto dinámico

- **Regla 1 — Es _input_, no _programa_.** Concatenarlo a ciegas en el prompt es la receta del **prompt injection**. Todo contenido externo va **claramente delimitado** en el prompt, y nunca se le da al LLM permiso para interpretarlo como instrucciones.
- **Regla 2 — Cuesta dinero por petición.** El estático se paga una vez (token caching); el dinámico se reincluye en cada llamada. Adjuntar un PDF de 30 páginas en cada turno duplica fácil el coste de la sesión.
- **Regla 3 — Añade latencia que el usuario nota.** PDF: 1–3 s. Búsqueda web: 2–5 s. BBDD: otro round-trip. La diferencia entre un producto que se siente vivo y uno roto está aquí.

De ahí salen **tres mecanismos canónicos** para enriquecer un CAG en runtime **sin saltar todavía a RAG**.

## 1.3 Mecanismo 1 — Archivos adjuntos

El usuario sube un PDF de especificación. Dos caminos, y la elección no es trivial:

| | **Camino A — Multimodal directo** | **Camino B — Extracción local** |
|---|---|---|
| Flujo | PDF → Files API del proveedor → LLM multimodal | PDF → extracción local (`pypdf`, `PyMuPDF`, `Docling`) → LLM (solo texto) |
| Ventajas | Cero código de extracción; interpreta diagramas | Independiente del proveedor; control fino; **prepara el terreno para RAG** |
| Desventajas | Lock-in al proveedor; más tokens | Código que mantener; pierde lo visual |

**Camino A — el PDF viaja al LLM.** Subes el archivo a la Files API y lo referencias en el mensaje:

```python
import anthropic
client = anthropic.Anthropic()

with open("specification.pdf", "rb") as f:
    uploaded = client.beta.files.upload(file=("specification.pdf", f, "application/pdf"))

response = client.beta.messages.create(
    model="claude-opus-4-7", max_tokens=2048, betas=["files-api-2025-04-14"],
    messages=[{"role": "user", "content": [
        {"type": "document", "source": {"type": "file", "file_id": uploaded.id}},
        {"type": "text", "text": "Use this technical specification as additional context."},
    ]}],
)
```

La carga se paga **una sola vez** (la Files API guarda el archivo durante la conversación); los siguientes turnos referencian el `file_id`. Pega: lock-in al proveedor multimodal, más tokens (tokeniza texto **y** representación visual de cada página), y es todo-o-nada.

**Camino B — solo el texto viaja al LLM.** Extraes el contenido antes de la llamada:

```python
from pypdf import PdfReader
from io import BytesIO

def extract_text_from_pdf(file_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(file_bytes))
    return "\n\n".join(f"--- Page {i} ---\n{p.extract_text() or ''}"
                       for i, p in enumerate(reader.pages, start=1))
```

Y concatenas con **delimitadores claros** (`<transcript>…</transcript>`, `<attachments>…</attachments>`). Para PDFs de texto bastan `pypdf`/`PyMuPDF`; para escaneados o layout complejo, `Docling`/`MarkItDown`/`LlamaParse` (markdown estructurado, conservan tablas). Para Word, `python-docx`. Ventaja decisiva: **la lógica de extracción de hoy es la primera pieza del pipeline de chunking de RAG** (módulo 3).

> **Cómo elegir:** velocidad de desarrollo y no te importa el lock-in → A. Entender el flujo completo y prepararte para RAG → B. **Lo que NO se hace es implementar los dos en paralelo** — es una decisión arquitectónica, no una feature acumulable.

## 1.4 Mecanismo 2 — Búsqueda web

Necesario cuando la estimación toca tecnologías, precios o benchmarks posteriores al corte de conocimiento del modelo (ej.: "queremos usar Bun en vez de Node"). Tres aproximaciones:

- **Herramienta nativa del proveedor** (OpenAI, Anthropic): la habilitas y el modelo decide cuándo usarla. `tools=[{"type": "web_search"}]`. Lo más simple y mejor integrado con el razonamiento. Pega: **lock-in total** y la calidad depende del índice del proveedor.
  > **Tool nativa** = búsqueda web que el proveedor expone como herramienta de primera clase, ya cableada.
- **Servicio de búsqueda independiente** (**Tavily**, **Exa**, **Firecrawl**): devuelven resultados optimizados para LLMs (snippets largos, markdown limpio, ranking semántico). Lo expones como tool tuya:
  ```python
  from tavily import TavilyClient
  tavily = TavilyClient(api_key=settings.tavily_api_key)

  def web_search(query: str, max_results: int = 5) -> list[dict]:
      results = tavily.search(query=query, max_results=max_results)
      return [{"title": r["title"], "url": r["url"], "snippet": r["content"]}
              for r in results["results"]]
  ```
  Ventaja: independencia del proveedor, mismo wrapper para cualquier LLM. Pega: cableas tú el function calling, otra clave, otra factura.
- **SERP API tradicional** (`SerpAPI`, `Serper`): resultados crudos de Google/Bing; tú haces fetch, limpieza y resumen.
  > **SERP** = Search Engine Results Page; una API que te da los resultados crudos del buscador. Máximo control, máxima carga de mantenimiento. Para el `estimator` rara vez compensa.

> **Cuándo activarla:** solo si el modelo no puede responder con lo que ya sabe **y** la pregunta es sensible al tiempo (tecnologías de los últimos 6 meses, precios SaaS, benchmarks recientes, disponibilidad de librerías). Para patrones arquitectónicos, prácticas de equipo o riesgos típicos, el modelo ya lo sabe y la búsqueda **solo añade ruido**.

## 1.5 Mecanismo 3 — Consultas a la BBDD del backend de negocio

El más interesante. Quieres que la estimación considere los **proyectos similares que la empresa hizo antes** (horas reales, desviaciones, riesgos). Esos datos viven en la BBDD del backend de negocio, **no** en el servicio IA.

**Qué NO hacer: dar al servicio IA acceso directo a esa BBDD.** Error arquitectónico caro:
- **Acoplamiento de schema:** el servicio IA acaba conociendo el modelo de datos interno; cualquier cambio rompe ambos.
- **Permisos:** termina con credenciales de BBDD demasiado amplias y persistentes.
- **Lógica duplicada:** las reglas de negocio acaban implementadas en dos sitios.

> Cuando llegue RAG (módulo 3), la BBDD vectorial **sí** vivirá cerca del servicio IA — pero esa es la BBDD de **conocimiento del servicio IA**, no la **BBDD operacional del negocio**. La distinción importa.

**Qué SÍ hacer: function calling contra el backend.** El LLM invoca una tool; la implementación hace una llamada HTTP autenticada al backend, que resuelve contra su BBDD aplicando sus reglas y devuelve un payload limpio.

```
LLM ─(decide invocar tool)─► Servicio IA (Python) ─(HTTP autenticado)─►
Backend de negocio (Rails u otro) ─(consulta su BBDD con sus reglas)─► PostgreSQL del backend
```

El servicio IA define la tool y la implementa como cliente HTTP:

```python
similar_projects_tool = {
    "type": "function",
    "function": {
        "name": "find_similar_projects",
        "description": "Find historical projects with similar scope, technologies, team size. "
                       "Returns aggregated metrics on actual hours, deviations and risks.",
        "parameters": {"type": "object", "properties": {
            "technologies": {"type": "array", "items": {"type": "string"}},
            "team_size": {"type": "integer"},
            "scope_summary": {"type": "string"},
        }, "required": ["technologies", "scope_summary"]},
    },
}

async def find_similar_projects(technologies, scope_summary, team_size=None) -> dict:
    response = await http_client.post(
        f"{settings.business_backend_url}/api/internal/similar_projects",
        json={"technologies": technologies, "scope_summary": scope_summary, "team_size": team_size},
        headers={"Authorization": f"Bearer {settings.internal_api_token}"})
    response.raise_for_status()
    return response.json()
```

El backend expone el endpoint interno (aquí Rails, pero el patrón es **independiente del stack** — vale NestJS, Spring, Django, Go):

```ruby
# app/controllers/internal/similar_projects_controller.rb
module Internal
  class SimilarProjectsController < InternalApiController
    def create
      similar = Project.completed
        .with_any_technology(params[:technologies])
        .with_scope_similar_to(params[:scope_summary]).limit(5)
      render json: { projects: similar.map { |p| ProjectMetricsSerializer.new(p).as_json } }
    end
  end
end
```

> **Por qué es el patrón correcto:** preserva las tres capas limpias — el servicio IA solo sabe que existe la tool `find_similar_projects`; el backend mantiene la autoridad sobre las reglas; la BBDD operacional se accede solo desde donde debe. **El servicio IA y el backend se hablan por contrato HTTP, nunca por BBDD compartida** — regla que se mantiene incluso con RAG.

## 1.6 Combinar los tres: agentic loop, budget y trazabilidad

En un caso real coexisten: el usuario sube transcripción + PDF (mec. 1), el LLM decide que necesita precios de AWS (mec. 2) y consulta proyectos similares (mec. 3) antes de estimar. Lo orquesta el **agentic loop** que la Responses API ya implementa por defecto: tú expones las tools, el modelo decide la secuencia.

Dos disciplinas obligatorias en producción:
- **Budget de tokens.** System prompt + transcript + adjuntos + búsqueda + BBDD puede reventar la ventana de contexto. Define un máximo por turno y trunca/resume al superarlo.
- **Trazabilidad.** Cada tool invocada es un *span* observable. Conéctalo a la observabilidad de la Sesión 03 (`structlog` + Logfire/Langfuse). Un turno deja de ser una llamada y pasa a ser un **grafo de invocaciones** que necesita visibilidad de extremo a extremo.

## 1.7 Resumen: cuándo cada mecanismo

| Mecanismo | Cuándo | Coste principal | Latencia |
|---|---|---|---|
| **Adjuntos** | El usuario aporta documentación para esta petición | Tokens del documento | 1–3 s por documento |
| **Búsqueda web** | Pregunta sensible al tiempo o posterior al corte de entrenamiento | Tokens de snippets + factura del proveedor | 2–5 s por query |
| **BBDD del backend** | La respuesta debe basarse en datos propios (histórico, catálogo) | Round-trip HTTP + tokens del payload | 100–500 ms |

> **Las dos preguntas antes de añadir cualquier mecanismo:** ¿el modelo *podría* responder bien sin esto, o va a fallar de forma sistemática? ¿La latencia añadida degrada la experiencia más que el valor que aporta? El instinto "más contexto no hace daño" es falso: más contexto = más tokens, más latencia, más superficie de prompt injection, más debugging. **Arranca con el mínimo y añade contexto dinámico solo con evidencia.**

---

# PARTE 2 — Memoria conversacional vs historial

## 2.1 Definiciones

Son **dos cosas distintas** que se confunden:

> **Historial conversacional** = el array de mensajes (`system`, `user`, `assistant`…) que viaja a la API en cada llamada. Estructura **bruta**, cronológica. Responde a *"¿qué dijo el usuario en el turno 7?"*.
> **Memoria conversacional** = los **hechos destilados** que el sistema ha aprendido ("el proyecto se llama BookFlow", "el equipo son 3 full-time", "el cliente rechazó microservicios"). **Es independiente del turno: persiste aunque el turno original se descarte.** Responde a *"¿qué sabemos del proyecto?"*.

**Por qué separarlas:**
- **Coste y latencia.** El historial crece linealmente; la memoria no (20 hechos tras 100 turnos). Reenvías los hechos sin pagar el historial completo.
- **Resistencia al truncado.** Si la memoria depende del historial, desaparece al truncar. Si es independiente, sobrevive.
- **Auditabilidad.** "¿Por qué el LLM asumió X?" — si los hechos están en estructura inspeccionable, puedes responder.

## 2.2 Anatomía del estado conversacional

Una sesión tiene **tres componentes**, no uno:

```
Session
├── session_id: UUID v4
├── history (lo bruto)              ── crece linealmente, sufre truncado de ventana
└── project_metadata (lo destilado) ── crece solo con hechos nuevos, sobrevive al truncado
      ├── project_name: BookFlow   ├── technologies: Rails, React
      ├── assumed_team_size: 3      └── rejected_options: microservicios
```

```python
from pydantic import BaseModel, Field
from datetime import datetime
from uuid import uuid4

class ProjectMetadata(BaseModel):
    """Distilled facts. Survives history truncation. Updated after each turn."""
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

La separación es **estructural**. Cada turno el sistema hace 3 cosas en orden: (1) **inyecta** `project_metadata` en el system prompt vía template + la ventana actual de `history`; (2) **llama** al LLM; (3) **actualiza** `history` (par user/assistant) y `project_metadata` (hechos nuevos). Los pasos 1 y 3 son lo interesante.

## 2.3 Inyectar la memoria en el system prompt

El template recibe un bloque `<project_metadata>` que arranca vacío y se va poblando:

```jinja2
You are a senior software estimation expert. Produce realistic, well-justified estimates...

{% if project_metadata %}
<project_metadata>
{% if project_metadata.project_name %}Project name: {{ project_metadata.project_name }}{% endif %}
{% if project_metadata.mentioned_technologies %}Technologies: {{ project_metadata.mentioned_technologies | join(", ") }}{% endif %}
{% if project_metadata.rejected_options %}Rejected (do not propose again): {% for o in project_metadata.rejected_options %}{{ o }} {% endfor %}{% endif %}
</project_metadata>
{% endif %}

When producing the estimate, treat the project_metadata as established facts.
Do not contradict them unless the user explicitly revises them in the current turn.
```

Dos detalles clave:
- **Renderizado condicional.** Cada campo solo si tiene valor — evita que el LLM vea `Project name: None` (ensucia el contexto e induce a inventar).
- **"Treat as established facts" no es decorativo.** Sin esa instrucción el LLM trata la memoria como una sugerencia y renegocia hechos cerrados. Con ella, la memoria tiene **autoridad**: aunque el turno donde se dijo "vamos con Rails" haya caído de la ventana, el hecho sigue ahí y el modelo no vuelve a preguntar el stack.

## 2.4 Actualizar la memoria tras cada turno

Inyectar es fácil; **mantenerla viva** es lo interesante. Dos aproximaciones:

**Aproximación 1 — Heurística simple** (regex + vocabulario conocido):

```python
import re
KNOWN_TECHNOLOGIES = {"rails", "react", "postgresql", "redis", "node", "python", ...}

def update_metadata_heuristic(metadata, user_turn, assistant_turn):
    combined = f"{user_turn}\n{assistant_turn}".lower()
    if metadata.project_name is None:
        m = re.search(r"(?:project (?:is )?(?:called|named) )['\"]?([A-Za-z0-9]+)", combined)
        if m: metadata = metadata.model_copy(update={"project_name": m.group(1)})
    found = {t for t in KNOWN_TECHNOLOGIES if t in combined}
    if found:
        merged = sorted(set(metadata.mentioned_technologies) | found)
        metadata = metadata.model_copy(update={"mentioned_technologies": merged})
    return metadata
```
- *A favor:* coste cero por turno, latencia despreciable, predecible y depurable.
- *En contra:* **frágil**. La regex asume una formulación concreta en inglés ("let's call it Bookflow internally" no la captura); las heurísticas crecen hasta ser un mini-NLP propio difícil de mantener.

**Aproximación 2 — LLM extractor** (segunda llamada que devuelve el `ProjectMetadata` actualizado en JSON):

```python
EXTRACTION_PROMPT = """
You receive the current ProjectMetadata and the latest turn. Produce an updated ProjectMetadata.
Rules:
- Only update fields when the turn provides clear evidence.
- Preserve existing values unless the user explicitly revises them.
- If the user retracts a fact, remove it.
- For lists, append new items without duplicating.
Current metadata: {current_metadata_json}
Latest turn: USER {user_turn} ASSISTANT {assistant_turn}
Return ONLY valid JSON matching the ProjectMetadata schema.
"""

async def update_metadata_llm(metadata, user_turn, assistant_turn, client):
    response = await client.responses.create(
        model="gpt-4o-mini",
        input=EXTRACTION_PROMPT.format(current_metadata_json=metadata.model_dump_json(),
                                       user_turn=user_turn, assistant_turn=assistant_turn),
        response_format={"type": "json_object"})
    return ProjectMetadata.model_validate_json(response.output_text)
```
- *A favor:* robusto ante variaciones de lenguaje, multilingüe gratis, capta hechos sutiles. Reutiliza el patrón de salida estructurada de la Sesión 04.
- *En contra:* una llamada extra por turno (céntimos, no cero), latencia +500–1500 ms, y un **riesgo nuevo**: si el extractor inventa un hecho falso, contamina todas las llamadas siguientes.

> **Cómo elegir:** dominio acotado y formulaico → heurística. Dominio abierto/multilingüe → LLM extractor. Con presupuesto para ambos → LLM extractor + validación heurística posterior. Para el `estimator` (conversación libre, posiblemente bilingüe) la balanza se inclina al **LLM extractor**, pero la heurística es defendible si quieres minimizar coste y latencia.

## 2.5 Las estrategias de historial vuelven (y se simplifican)

| Estrategia | Cómo funciona | Cuándo |
|---|---|---|
| **Ventana deslizante** | Mantiene los últimos N turnos, descarta los antiguos | Conversaciones cortas, o cuando los hechos ya viven en `project_metadata` |
| **Resumen acumulativo** | Resume los turnos antiguos en un mensaje compacto | Conversaciones largas donde el matiz del lenguaje original importa |
| **Híbrida con anclas** | Resumen de lo antiguo + ventana de los últimos N + turnos críticos que nunca se descartan | Producción seria, conversaciones de días/semanas |

> **La consecuencia más importante de separar memoria e historial:** la decisión de qué estrategia usar se vuelve **menos crítica**. La ventana deslizante deja de ser arriesgada porque los hechos que importan ya no se pierden al caer un turno. **Ventana deslizante con `MAX_TURNS = 6` + `project_metadata` actualizado por turno es una arquitectura razonable para producción inicial.**

## 2.6 Cuándo olvidar: tres políticas, tres ubicaciones

Sin olvido, la memoria crece sin control y los hechos viejos contaminan decisiones nuevas. Son **tres mecanismos independientes**, no uno:

- **Política 1 — Revisión explícita del usuario.** "Ya no usamos Rails, vamos con Node" → `mentioned_technologies` actualizada, `rejected_options` ampliada. Vive en la **lógica de actualización de memoria**.
- **Política 2 — TTL por sesión.** Una sesión inactiva 24 h probablemente ya no es la misma conversación; se archiva y al reanudar se ofrece sesión nueva. Vive en el **ciclo de vida de la sesión** (job programado).
  > **TTL** (Time To Live) = tiempo tras el cual algo caduca automáticamente.
- **Política 3 — Reset explícito.** El usuario debe poder decir "olvida todo". Un `POST /sessions` crea una sesión limpia y deja la anterior intacta para auditoría. Es un **endpoint REST** normal.

## 2.7 Persistencia y anti-patrones

**Persistencia (no entra todavía).** En una arquitectura madura las sesiones viven en BBDD (Redis para acceso rápido, PostgreSQL para auditoría); el servicio IA recibe el `session_id` y carga el estado. Ahora la elección razonable es un **diccionario en memoria** del proceso: simple, no escala más allá de un proceso, se pierde al reiniciar. Se acepta porque persistencia y federación son del módulo de despliegue. Clave: **la separación `history` / `project_metadata` sobrevive intacta** — ambos se serializan por separado; migrar de dict a Redis no requiere refactor del modelo.

**Anti-patrones:**
- **AP1 — Memoria como string libre en el system prompt.** Funciona en el turno 1; en el turno 20 está lleno de inconsistencias. Una estructura tipada es más larga pero infinitamente más mantenible.
- **AP2 — Confiar en que el LLM "se acordará".** El LLM **no tiene estado entre llamadas**. Si el turno cayó de la ventana, el hecho desaparece salvo que viva explícitamente en otro lado. La memoria explícita es la única forma de que el hecho sobreviva.
- **AP3 — Mezclar memoria e historial en una estructura.** "Guardo todo en un blob". La factura llega cuando necesitas truncar el historial sin tocar la memoria, o migrar conversaciones antiguas tras un cambio de schema.

> **Las cuatro afirmaciones:** (1) historial y memoria son estructuras distintas con responsabilidades distintas; (2) la memoria sobrevive al truncado; (3) se materializa como estructura tipada (Pydantic), inyectada vía template y actualizada cada turno; (4) el olvido necesita políticas explícitas.

---

# PARTE 3 — Prompts adaptativos por perfil: el patrón "tier"

## 3.1 El antipatrón del prompt único

El `estimator` tiene un único system prompt: todos reciben el mismo formato. Pero dos usuarios distintos piden lo mismo con necesidades opuestas:

- **Developer senior:** desglose por componentes (backend, frontend, infra, integraciones), horas por componente, riesgos técnicos, asunciones de stack.
- **Director comercial:** coste agregado, rango de duración, hitos visibles, confianza global. No le sirve "12h en config de PostgreSQL"; le sirve "Fase 1: Setup — 2 semanas, riesgo bajo".

El sistema actual les da a ambos **la misma respuesta**. Consecuencia: los usuarios empiezan a escribir "dame solo el resumen ejecutivo" — y reaparece el patrón que combatimos en la Sesión 04 (la calidad del output dependiendo del prompt del usuario). **La interfaz vuelve a ser un chat encubierto.**

> El instinto de un equipo senior ante "responder distinto según quién pregunta" es pensar en fine-tuning o RLHF. La respuesta correcta es mucho menos glamurosa: **una columna `tier` en la tabla de usuarios, un `if/elif` que elige plantilla, y schemas de salida distintos.**

## 3.2 Tres capas, cada una en un sitio

```
Capa 1 — Persistencia (backend)   users.tier (BBDD): developer | pm | executive   ── NO es autorización, es dimensión de producto
Capa 2 — Propagación              JWT con claim tier  ·  o header en red privada
Capa 3 — Materialización (IA)     template Jinja2 + schema Pydantic por tier
```

**Capa 1 — el tier vive en la BBDD del backend.** Columna enumerada:

```ruby
class AddTierToUsers < ActiveRecord::Migration[7.1]
  def change
    add_column :users, :tier, :string, null: false, default: "developer"
    add_index :users, :tier
  end
end

class User < ApplicationRecord
  TIERS = %w[developer pm executive].freeze
  validates :tier, inclusion: { in: TIERS }
end
```

> El tier **no es un rol de autorización** (qué *puede hacer* el usuario) — eso vive en otra columna. Es una **dimensión de producto** (qué *experiencia* recibe). Importa porque un mismo rol puede mapear a tiers distintos: un developer puede pedir el modo `executive` para una presentación al comité.

**Capa 2 — el tier viaja al servicio IA.** Dos maneras:
- **JWT firmado por el backend** que el servicio IA valida (correcto a medio plazo: defensa en profundidad, permite añadir claims —timezone, idioma, org_id— sin renegociar contratos):
  > **JWT** (JSON Web Token) = un token firmado que transporta datos (claims) verificables sin volver a consultar al backend.
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
- **Header simple** en una red controlada (backend y servicio IA en la misma VPC; la confianza la da la red, no la cripto). Razonable mientras todo viva en una sola red privada.

**Capa 3 — el tier selecciona template y schema.** Aquí deja de ser metadata y se vuelve **comportamiento**:

```python
class DeveloperEstimate(BaseModel):
    components: list[ComponentEstimate]; technical_risks: list[str]
    stack_assumptions: list[str]; uncertainty_drivers: list[str]; total_hours_range: tuple[int, int]

class PmEstimate(BaseModel):
    phases: list[PhaseEstimate]; milestones: list[Milestone]
    team_composition: TeamComposition; duration_weeks_range: tuple[int, int]; blockers: list[str]

class ExecutiveEstimate(BaseModel):
    headline_cost_range: CostRange; headline_duration_range: DurationRange
    confidence_level: Literal["low", "medium", "high"]; top_three_risks: list[str]; go_no_go_recommendation: str

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

Y el endpoint queda limpio: `resolve_tier_config(caller.tier)` → renderiza el template → llama al LLM con `response_format` = el `model_json_schema()` del schema → valida la salida.

> **Eso es todo el patrón.** La sofisticación está en haber tomado la decisión correcta, no en el código.

## 3.3 Diseñar los templates por tier

Comparten estructura (rol, contexto CAG, transcripción, formato) y se diferencian en **instrucciones**. `developer`: desglosa por componente técnico, horas/riesgos/asunciones por componente, habla a ingenieros como pares. `executive`: lidera con un rango de coste y uno de duración (sin desglose), confianza global con una justificación, top-3 riesgos, recomendación go/no-go, sin jerga.

Tres detalles:
- **Reutilización con `include`.** Los bloques compartidos (`_project_metadata.j2`, `_reference_estimates.j2`) viven en parciales que los tres importan. Cambias el CAG estático en un sitio.
- **Las instrucciones se diferencian, el formato no se mezcla.** `developer` no dice "más detalle"; dice *qué dimensiones* lo componen. `executive` no dice "sé conciso"; especifica *qué piezas* lleva. El modelo trabaja mejor con instrucciones específicas.
- **El schema es el segundo guardrail.** Aunque el template indique qué devolver, `response_format` con `json_schema` lo *fuerza*: si el LLM olvida una sección, la validación falla y el sistema lo detecta antes de que el usuario reciba algo defectuoso.

## 3.4 Cómo gestionar la evolución de tiers

¿Y cuando hace falta un cuarto tier? La respuesta **no** es añadir entradas a `TIER_CONFIG` indefinidamente:
- **H1 — Tres es el número para arrancar.** Cubre la mayoría sin fragmentar. Si necesitas más, lo descubrirás por evidencia, no por anticipación.
- **H2 — Tier compuesto = señal de tier mal definido.** Si necesitas "executive con un poco de developer", probablemente al `executive` le falta una sección de "appendix técnico". Casi siempre es más barato **refinar** un tier que multiplicarlos.
- **H3 — Nuevos tiers exigen evaluación, no intuición.** Cada tier = template + schema + casos de prueba. Sin golden dataset que valide que produce respuestas distintas y de calidad, añades complejidad sin valor verificable.

## 3.5 El antipatrón paralelo: el tier que solo cambia el tono

Parece bien, funciona en la demo, se rompe en producción: **un único schema y template** con un "responde en {tono} según el tier":

```jinja2
{% if tier == "executive" %}Respond in an executive tone, focused on strategic implications.
{% elif tier == "pm" %}Respond in a project management tone, focused on phases and risks.
{% else %}Respond in a technical tone with implementation detail.{% endif %}
```

Funciona porque los modelos adaptan el tono. **Falla porque la _estructura_ es la misma para todos**, y la estructura es donde vive el valor. El ejecutivo sigue recibiendo una respuesta organizada por componentes técnicos, solo que con palabras menos técnicas.

> **Regla operativa: adaptar un CAG a perfiles significa adaptar la _estructura de salida_, no solo el tono.** Si el tier no cambia el schema Pydantic, probablemente es lock-in cosmético, no diseño de producto.

## 3.6 Cuando un tier merece su propia pipeline (deep research)

Hasta aquí los tres tiers comparten **la misma pipeline** (una llamada con template + schema). El patrón superior: **un tier puede activar una pipeline completamente distinta.** Ejemplo paradigmático, el *Deep Research* de OpenAI: modelo distinto (`o3-deep-research`), web search por defecto, modo `background` de minutos, informe largo con citas.

```python
TIER_CONFIG = {
    "developer": {"pipeline": "single_call", "template": "estimate_developer.j2", "schema": DeveloperEstimate, "model": "gpt-4o-mini"},
    "pm":        {"pipeline": "single_call", ...},
    "executive": {"pipeline": "single_call", ...},
    "research":  {"pipeline": "deep_research", "template": "estimate_research.j2", "schema": ResearchEstimate,
                  "model": "o3-deep-research", "tools": ["web_search", "code_interpreter"],
                  "background": True, "estimated_latency_seconds": 600, "estimated_cost_per_call_eur": 5.00},
}
PIPELINE_HANDLERS = {"single_call": run_single_call_pipeline, "deep_research": run_deep_research_pipeline}

async def estimate(...):
    config = resolve_tier_config(caller.tier)
    handler = PIPELINE_HANDLERS[config["pipeline"]]
    return await handler(config, session, transcript, attachments)
```

El tier `research` cuesta **minutos** (no segundos) y **euros** (no céntimos); la interfaz lo refleja (avisa del tiempo, permite cerrar la pestaña y recibir el resultado por email, descarga en PDF).

> **La lección:** el patrón tier escala desde "mismo motor, distinta presentación" hasta "motor completamente distinto". Conocer ese rango cambia cómo diseñas la abstracción desde el principio.

## 3.7 Anti-patrones

- **AP1 — El tier vive en el frontend.** "Mi cliente envía `tier` en el body y el servicio IA lo respeta": cualquiera envía `tier=executive` y accede al modo más caro. **El tier debe vivir en la BBDD del backend y propagarse por un canal que el cliente no pueda manipular.**
- **AP2 — Un solo schema con branching de campos.** "Un `EstimateOutput` con todos los campos y el modelo rellena los que tocan": deja de ser un contrato (el modelo rellena campos que no debería, el cliente no sabe qué esperar). **Schemas separados = más código pero contrato nítido.**
- **AP3 — Templates por tier que divergen sin disciplina.** Empiezas con tres compartiendo el 80%; tres meses después cada uno fue por su cuenta y los bloques compartidos están duplicados. **Parciales con `include` no es opcional** cuando los templates se multiplican.

---

# PARTE 4 — Testing y evaluación de sistemas con LLMs

## 4.1 Por qué `assert response == "expected"` no funciona

```python
def test_estimate_basic_project():
    result = estimator.estimate("Build a simple landing page in HTML and CSS")
    assert result.total_hours == 16
```

Este test **falla el 30% de las veces aunque el sistema funcione perfectamente**: la misma transcripción da 14, 16, 18, o "rango 10–22 con confianza media", y las cuatro son correctas. La igualdad estricta produce dos errores:
- **Falsos negativos masivos.** Falla porque el modelo dijo "16 horas" y esperabas "16h". Alguien añade `if "16" in result` y la suite "pasa por casualidad". La señal se ha perdido.
- **Falsos positivos silenciosos.** Pasa porque compruebas que el resultado es un string de longitud > 0. En producción devuelve "Lo siento, no puedo ayudarte" para cualquier input y los tests siguen verdes.

> **La conclusión:** en sistemas con LLM el test no comprueba *igualdad* sino **propiedades**. Para el `estimator`: el output es JSON válido contra el schema, las horas caen en un rango razonable, menciona los componentes de la transcripción, no contradice `project_metadata`, mantiene consistencia entre invocaciones.

## 4.2 Las tres familias (la pirámide)

```
        ╱╲  Familia 3: Calidad subjetiva (LLM-as-judge, GEval) — pocos · caro, lento, valioso
       ╱──╲
      ╱    ╲  Familia 2: Determinismo soft (consistencia entre runs) — algunos · medio
     ╱──────╲
    ╱        ╲ Familia 1: Determinismo hard (schema, rangos, campos; SIN llamada extra) — muchos · barato
   ╱──────────╲
```

**Familia 1 — Deterministas _hard_.** La propiedad **no depende del modelo**: la respuesta es input opaco y la verificación es estructural/numérica, sin otra llamada al LLM. **La primera capa, siempre:**

```python
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
    assert all(c.name.strip() for c in result.components)
```
> Si el equipo no tiene cobertura mínima en esta familia, **cualquier discusión sobre LLM-as-judge es prematura.**

**Familia 2 — Deterministas _soft_.** Propiedades **estadísticas**: ejecutas N veces el mismo input y verificas que la *distribución* tiene la forma esperada. El caso típico es la **consistencia**:

```python
import statistics

@pytest.mark.asyncio
async def test_estimate_consistency():
    transcript = "Build a simple landing page with contact form."
    results = [await estimate(tier="developer", transcript=transcript) for _ in range(5)]
    midpoints = [(r.total_hours_range[0] + r.total_hours_range[1]) / 2 for r in results]
    cv = statistics.stdev(midpoints) / statistics.mean(midpoints)
    assert cv < 0.25, f"Inconsistent estimates: CV={cv}, midpoints={midpoints}"
```
> **Coeficiente de variación (CV)** = desviación estándar / media; mide la variabilidad relativa. Se acepta hasta 25%.

Más caros (5 llamadas/test) y lentos. Detectan un fallo que ningún test hard ve: que el sistema responda *correctamente* pero con varianza inaceptable. Córrelos en CI antes de merge, no en cada commit local.

**Familia 3 — Calidad subjetiva (LLM-as-judge).** La propiedad es genuinamente subjetiva (¿la justificación es coherente con el alcance? ¿menciona los riesgos relevantes?). Solo un juez —humano o LLM— la valora.

> **LLM-as-judge** = una segunda llamada al LLM con un prompt de evaluación que emite un veredicto. Dos modos: **pointwise** (puntúa 0–1) y **pairwise** (compara dos respuestas).
> **DeepEval** = framework de evaluación de LLMs sobre pytest. Su métrica **`GEval`** encapsula el LLM-as-judge.

```python
from deepeval import assert_test
from deepeval.test_case import LLMTestCase, SingleTurnParams
from deepeval.metrics import GEval

def test_estimate_justification_coherence():
    estimate_result = run_estimate_sync(tier="developer", transcript="Build a simple landing page with contact form.")
    coherence = GEval(
        name="JustificationCoherence",
        criteria="Determine whether the technical risks in the actual output are coherent "
                 "with the project scope in the input. Coherent = plausible risks, no irrelevant ones.",
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        threshold=0.7)
    test_case = LLMTestCase(input="Build a simple landing page with contact form.",
                            actual_output=estimate_result.model_dump_json())
    assert_test(test_case, [coherence])
```
Tres precauciones: (1) **el juez también es un LLM y también se equivoca** (puede preferir respuestas largas); calíbralo contra veredictos humanos. (2) **El umbral importa más que la métrica** — 0.7 no es universal; empieza en 0.5 y ajusta. (3) **No abuses** — cada test es una llamada extra. *Si una propiedad se puede testear con un regex, no la testees con un juez.*

## 4.3 El golden dataset

Una transcripción de prueba basta para la mecánica pero no para evaluar en serio. El **golden dataset** es un conjunto **curado** de casos representativos, cada uno **anotado con el comportamiento esperado**. Para el `estimator`, 5–15 transcripciones que cubran el espectro real:
- Proyecto simple bien acotado (landing, formulario).
- Proyecto medio multi-componente (panel admin con auth y reportes).
- Proyecto grande con dependencias externas (3 APIs de pago, cola asíncrona).
- Caso ambiguo sin detalles críticos.
- Caso límite con contradicciones internas.
- Caso multilingüe si el sistema lo soporta.

Cada caso lleva metadata (categoría, horas que estimaría un experto, riesgos clave, componentes esperados).

> **Esa metadata es lo que lo hace _golden_:** no es una lista de inputs, es una lista de inputs **con sus criterios de éxito**.

```python
from deepeval.dataset import EvaluationDataset, Golden

golden_dataset = EvaluationDataset(goldens=[
    Golden(input="Build a simple landing page with contact form.", expected_output=None,
           additional_metadata={"category": "small_project", "expected_hours_range": (16, 40),
                                "expected_components": ["frontend", "form_handling"]}),
    Golden(input="We need an internal admin dashboard with user management, role-based permissions, "
                 "audit log, and weekly email reports.",
           additional_metadata={"category": "medium_project", "expected_hours_range": (200, 400),
                                "expected_components": ["backend", "frontend", "auth", "reporting"]}),
    # ... más goldens
])
```

Construirlo es trabajo (un caso bien anotado puede costar 1 h de experto). **Es una inversión, no un coste:** se amortiza en la primera regresión que evita. Heurísticas: representa la distribución real (no inventes casos exóticos), al menos un caso límite por categoría, y **revísalo cada tres meses**.

## 4.4 Suite con DeepEval + pytest

DeepEval encadena las tres familias sobre el golden dataset (nativo pytest, sin infra externa). Patrón completo:

```python
import pytest, statistics
from deepeval import assert_test
from deepeval.test_case import LLMTestCase, SingleTurnParams
from deepeval.metrics import GEval
from tests.fixtures import golden_dataset

# Familia 1 — Hard
@pytest.mark.parametrize("golden", golden_dataset.goldens)
def test_schema_validity(golden):
    assert isinstance(estimate_sync(tier="developer", transcript=golden.input), DeveloperEstimate)

@pytest.mark.parametrize("golden", golden_dataset.goldens)
def test_hours_within_expected_range(golden):
    low, high = estimate_sync(tier="developer", transcript=golden.input).total_hours_range
    exp_low, exp_high = golden.additional_metadata["expected_hours_range"]
    assert low >= exp_low * 0.5 and high <= exp_high * 1.5   # 50% de holgura en primera pasada

# Familia 2 — Soft
@pytest.mark.slow
@pytest.mark.parametrize("golden", golden_dataset.goldens[:3])  # solo una muestra
def test_consistency_across_runs(golden):
    results = [estimate_sync(tier="developer", transcript=golden.input) for _ in range(3)]
    midpoints = [(r.total_hours_range[0] + r.total_hours_range[1]) / 2 for r in results]
    assert statistics.stdev(midpoints) / statistics.mean(midpoints) < 0.25

# Familia 3 — LLM-as-judge
coherence_metric = GEval(name="ScopeCoherence",
    criteria="Evaluate whether components and risks in the output match the project scope. "
             "Penalize components or risks not implied by the scope.",
    evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT], threshold=0.7)

@pytest.mark.slow
@pytest.mark.parametrize("golden", golden_dataset.goldens)
def test_scope_coherence(golden):
    result = estimate_sync(tier="developer", transcript=golden.input)
    assert_test(LLMTestCase(input=golden.input, actual_output=result.model_dump_json()), [coherence_metric])
```

Tres detalles operativos:
- **`@pytest.mark.slow`.** Permite correr solo la suite rápida en local (`pytest -m "not slow"`) y reservar la completa para CI. Sin esta separación, el equipo deja de correr la suite.
- **Parametrización con el golden dataset.** Cada test corre una vez por golden → tres tests se vuelven 30-40 casos sin duplicar código, y pytest reporta cada combinación por separado.
- **Tolerancias generosas en la primera pasada.** El 50% de desviación es deliberado: primero quieres pillar fallos catastróficos (una landing en 800 h), no microajustes. Cuando madure, aprietas.

## 4.5 Anti-patrones y lo que no cubre todavía

**Anti-patrones:**
- **AP1 — Testar la respuesta del modelo, no las propiedades de tu sistema.** "Respondió 16 en vez de 18, ajusto el test": el test memoriza salidas; cuando OpenAI actualiza el modelo, todo rompe y crees que hay un bug inexistente. Testa propiedades.
- **AP2 — Suite que es solo familia 3.** Lentísima, carísima, y todos los tests dependen del mismo punto de fallo (el juez). Una suite sana es **piramidal**. *Si el cuerpo está en la cima, algo va mal.*
- **AP3 — Golden dataset que se construye una vez y se olvida.** Lo representativo en febrero deja de serlo en agosto. Tests verdes y producción fallando. Revísalo cada trimestre.

**Lo que esta primera exposición NO cubre** (se trata en la Sesión 15, LLMOps):
- **Métricas para RAG** (faithfulness, contextual precision, answer relevancy). Framework: **RAGAS**.
- **Tests de regresión en CI/CD** (bloquear merges si el score cae).
- **Monitoring en producción** (online evals sobre tráfico real). **Langfuse**, **Confident AI**, **Logfire**.
- **Red teaming automatizado** (inputs adversariales). **Promptfoo**.
- **Datasets sintéticos** (generar casos con LLM desde un seed pequeño).

> **Las cuatro afirmaciones:** (1) el test unitario clásico no aplica a outputs de LLM — testa propiedades; (2) tres familias con costes y propósitos distintos, en proporción piramidal; (3) el golden dataset es la base de todo lo demás; (4) DeepEval + pytest cubre la base mínima sin infra externa.

---

# PARTE 5 — Actor-Critic-Boss: la composición de roles que eleva la calidad

## 5.1 Por qué un mejor prompt no es la solución

A estas alturas el `estimator` es serio (adjuntos, memoria separada, tiers, evals). Y aun así hay un **techo de calidad que no se rompe refinando prompts**: aritméticas que no cuadran, riesgos importantes sin mencionar, componentes que aparecen en la justificación pero no en el desglose, casos límite donde el modelo elige sin verificar.

El punto donde el prompt deja de funcionar es donde el problema **no es de instrucción, sino de verificación.** Cuando un humano produce una estimación importante no hace "pienso una respuesta y la entrego", sino *"pienso, reviso, encuentro un error, corrijo, vuelvo a revisar"*. Esa segunda pasada es **estructuralmente distinta** de la generación: usa criterios explícitos, va a contracorriente del razonamiento original, y descubre cosas que el generador no veía porque estaba comprometido con su narrativa.

> Un único LLM en una sola llamada hace ambas cosas a la vez, y los modelos no son buenos en autocrítica genuina. **Self-Refine (Madaan et al., 2023)** mostró que separar generación de feedback en dos llamadas mejora la calidad un **20% absoluto** de media sobre 7 tareas, sin entrenamiento. **Mezclar generación y verificación en una misma llamada degrada ambas.**

## 5.2 Los tres roles

Cada rol es una llamada al LLM con su propio prompt y criterio de éxito:

```
Entrada (transcript + metadata)
   │
   ▼  ┌─────────┐  candidate_estimate
      │  ACTOR  │ ────────────────────►┐
      └─────────┘                      ▼
      ┌─────────┐  feedback         ┌─────────┐
      │ CRITIC  │ ◄──────────────── │  BOSS   │  aceptar / iterar / sintetizar
      └─────────┘   (iterar máx 2-3) └─────────┘
                                         │ final_estimate
                                         ▼
```

- **Actor.** Genera la estimación inicial (transcripción + adjuntos + `project_metadata`). **Es la llamada que el `estimator` ya hace; no cambia** (template por tier, schema, contexto CAG). Lo único: su salida deja de ser final y pasa a ser un **candidato**.
- **Critic.** Recibe el output del actor y lo evalúa contra criterios explícitos: ¿completo? ¿la aritmética cuadra? ¿riesgos coherentes con el alcance? ¿contradicciones con `project_metadata`? ¿faltan componentes? **NO genera una nueva estimación: produce _feedback estructurado_.**
- **Boss.** Recibe estimación + feedback y **decide**: sin problemas materiales → acepta; problemas corregibles → devuelve al actor con instrucciones; feedback complejo → sintetiza la versión final. Y **limita las iteraciones** para acotar coste y latencia.

## 5.3 Anclaje en la literatura

El nombre es del programa, pero los roles tienen base sólida:

| Rol | Equivalente | Fuente |
|---|---|---|
| **Actor** | Generator / Optimizer | Anthropic, *Building Effective Agents* (2024); Madaan, *Self-Refine* (2023); Estornell, *ACC-Collab* (2024) |
| **Critic** | Evaluator / Self-Verifier | Anthropic, *Building Effective Agents*; *Self-Refine*; Shinn, *Reflexion* (2023) |
| **Boss** | Orchestrator / Supervisor | Anthropic, *Building Effective Agents* (orchestrator-workers); *LLaMAC* (2023) |

*Building Effective Agents* (Anthropic) formaliza los dos workflows base: **Evaluator-Optimizer** (uno genera, otro evalúa, se itera → `actor + critic`) y **Orchestrator-Workers** (uno central descompone, delega y sintetiza → `boss`). Lo que **añade Actor-Critic-Boss** sobre Self-Refine puro es la **separación explícita entre evaluación y decisión**.

## 5.4 Por qué tres roles y no dos

Si el crítico **también decide** qué hacer con su feedback, aparecen dos modos de fallo reportados en Self-Refine puro:
- **Bucles infinitos por insatisfacción crónica.** Un crítico bien calibrado casi siempre encuentra algo que mejorar; sin árbitro externo, el sistema itera con mejoras marginales agotando presupuesto. El problema no es del crítico: **evaluar y decidir cuándo parar son funciones diferentes.**
- **Sesgo de confirmación temprana.** El opuesto: el crítico se vuelve cómplice del actor y acepta la primera respuesta. Fuerte cuando el mismo LLM hace de crítico y actor (tiende a defender lo que acaba de producir).

> **Separar evaluación de decisión rompe ambos.** El crítico se concentra en feedback de calidad; el boss, con prompt y criterios distintos —centrados en *governance* del proceso, no en calidad técnica—, decide cuándo lo bueno es suficiente. Paralelo humano: el ingeniero hace el trabajo, el revisor identifica problemas, el tech lead decide cuáles bloquean el merge. **La especialización funciona.**

## 5.5 Cuándo compensa y cuándo es overkill

Triplica las llamadas (mínimo) y multiplica la latencia. **Compensa con al menos dos** de estas condiciones:
- **El coste del error es alto.** Base de un contrato comercial, recomendación médica, análisis de inversión. Una respuesta defectuosa cuesta más que la latencia.
- **Hay criterios de evaluación claros.** El crítico necesita instrucciones específicas; si son "que esté bien", degenera. Para el `estimator` son claros: aritmética, completitud de componentes, coherencia con la transcripción.
- **La latencia adicional es tolerable.** En un chat con expectativa de respuesta inmediata, ×3 rompe la experiencia; en un informe que el usuario recibe cuando esté listo, los segundos extra valen.

**Es overkill cuando:** la tarea es simple y difícilmente errónea ("traduce este texto"); ya hay tests hard que cubren los fallos importantes; el coste por petición ya es crítico; o los criterios son tan vagos que el crítico no aporta.

> **Regla operativa: aplica el patrón solo a los _caminos críticos_, no a todas las llamadas.** Para el `estimator`: a la generación de estimación final, no a la extracción de `project_metadata` ni a respuestas auxiliares.

## 5.6 Anti-patrones

- **AP1 — Tres llamadas con casi el mismo prompt.** Pagas tres veces sin ganancia. **Cada rol necesita un prompt estructuralmente distinto:** actor optimiza generación, crítico optimiza detección de fallos, boss optimiza gobernanza del proceso.
- **AP2 — El crítico devuelve texto libre.** El boss recibe un párrafo, lo interpreta mal, y el sistema se vuelve menos predecible que el monolítico de partida. **El feedback debe ser estructurado:** lista de issues con categoría (`arithmetic_error`, `missing_component`, `inconsistency_with_metadata`…), severidad (`critical`/`major`/`minor`) y campo afectado. La disciplina de schemas Pydantic aplica directa.
- **AP3 — Iteraciones sin límite.** "El boss para cuando el crítico no encuentre más problemas": en la práctica siempre encuentra algo. **El boss opera con un presupuesto máximo (típicamente 2 o 3);** al agotarse, sintetiza la mejor respuesta disponible y la entrega aunque no sea perfecta. **Producción se prefiere a perfección.**

> Lo importante de esta pieza no es la implementación —directa— sino haber interiorizado **por qué** la separación de roles eleva la calidad. Cuando ese *por qué* está claro, el *cómo* se construye solo.

---

## Cómo conecta con nuestro ejercicio y con el directo

Las 5 partes no son temas sueltos: son **5 capas que se montan sobre el mismo `estimator`** y, juntas, lo vuelven producto. El orden no es casual:

1. **Contexto dinámico (P1)** amplía *qué información* entra, manteniendo el aislamiento entre capas (servicio IA ↔ backend por contrato HTTP). Es la antesala de RAG: la extracción de texto de adjuntos ya es la primera pieza del chunking.
2. **Memoria vs historial (P2)** da continuidad multi-turno sin reventar coste ni latencia. El `ProjectMetadata` tipado sobrevive al truncado y se inyecta en *todos* los templates siguientes.
3. **Patrón tier (P3)** adapta la *estructura de salida* al consumidor. Reutiliza la memoria (la inyecta en cada template) y la disciplina de schemas de la Sesión 04.
4. **Testing/evals (P4)** permite tocar las tres capas anteriores **sin miedo**. Sin evals, cada cambio de prompt es a ciegas; con evals, detectas regresiones antes que los usuarios.
5. **Actor-Critic-Boss (P5)** sube el techo del camino crítico (la estimación final), apoyándose en los criterios de evaluación que la P4 ya te obligó a explicitar.

> **Hilo transversal — la misma regla en las cinco:** *no añadas potencia (contexto, memoria, tiers, juez LLM, roles) por defecto. Añádela con evidencia, mide siempre el coste en tokens y latencia, y mantén el aislamiento entre capas.* La sofisticación vive en la arquitectura, no en el modelo.

**Divergencias de nuestro proyecto** (alineado al repo del profesor post-sesión-5, con decisiones propias): mantenemos Postgres único + telemetría propia + frontend Angular; cuando estas partes aterricen en código, el `ProjectMetadata`, el `TIER_CONFIG` y el flujo Actor-Critic-Boss se implementan sobre ese stack. Ver [session-08-theory](../session-08-datadrivenai-bbdd-vectoriales/session-08-theory-datadrivenai-bbdd-vectoriales.md) para la capa de persistencia vectorial (pgvector) que continúa esta línea en RAG.

---

## Chuleta de una página (lo imprescindible)

**P1 — Contexto dinámico.** Tres reglas: es *input* no programa (cuidado con prompt injection), cuesta por petición, añade latencia. Tres mecanismos: **adjuntos** (multimodal directo vs extracción local; extracción = terreno para RAG), **búsqueda web** (nativa / Tavily-Exa / SERP; solo si es sensible al tiempo), **BBDD del negocio** (function calling vía HTTP, NUNCA acceso directo). Los orquesta el *agentic loop*; controla budget de tokens + trazabilidad.

**P2 — Memoria vs historial.** **Historial** = array de mensajes bruto (qué se dijo). **Memoria** = hechos destilados (qué sabemos). La memoria sobrevive al truncado → materialízala como `ProjectMetadata` (Pydantic), inyéctala en el system prompt (renderizado condicional + "treat as established facts"), actualízala cada turno (heurística barata vs LLM extractor robusto). Olvido = 3 políticas (revisión usuario / TTL sesión / reset). Ventana deslizante `MAX_TURNS=6` + memoria separada = arquitectura razonable.

**P3 — Patrón tier.** Adaptar a perfiles = **desarrollo web normal**, no IA avanzada. Tres capas: tier en **BBDD del backend** (dimensión de producto, no autorización) → propagado por **canal autenticado** (JWT/header, NUNCA param del cliente) → materializa **template + schema por tier** en el servicio IA. Adaptar = cambiar la **estructura de salida** (schema distinto), no solo el tono. Escala hasta "pipeline completamente distinta" (deep research).

**P4 — Testing/evals.** `assert == expected` NO funciona; testa **propiedades**. Pirámide de **tres familias**: hard (estructural, barato, base) → soft (estadístico, consistencia/varianza, medio) → subjetivo (LLM-as-judge / DeepEval `GEval`, caro, cima). Base de todo: **golden dataset** (5-15 casos curados + criterios de éxito; inversión, no coste; revisión trimestral). Herramienta: DeepEval + pytest, `@pytest.mark.slow` + parametrización. Testa propiedades del sistema, no salidas del modelo.

**P5 — Actor-Critic-Boss.** Hay un techo que no rompe el prompt: el problema es de **verificación**, no de instrucción (Self-Refine: +20% separando generación de feedback). **Tres roles, no dos:** Actor genera, Critic **solo** evalúa (feedback estructurado), Boss **solo** decide (acepta/itera/sintetiza, límite 2-3 iteraciones). Separar evaluación de decisión rompe bucles infinitos + sesgo de confirmación. Anclado en *Building Effective Agents* (evaluator-optimizer + orchestrator-workers). Compensa si: coste del error alto + criterios claros + latencia tolerable. Solo en caminos críticos.
