# Sesión 02 — Arquitectura CAG (versión clara)

> Versión simplificada del resumen de los 5 artículos de la Sesión 2.
> Misma información, menos paja. Cada término técnico se explica en una frase.
> **Hilo conductor:** un consultor que estima presupuestos de software a partir de presupuestos antiguos que lleva ya "sobre la mesa".

---

## Glosario base (léelo una vez y vuelve cuando haga falta)

| Término | Qué es, en una frase |
|---|---|
| **LLM** | Modelo de lenguaje (GPT, Claude...) que genera texto; su conocimiento se congela en el entrenamiento y tiene fecha de corte. |
| **Inferencia** | El momento en que el modelo *responde* a una petición (no cuando se entrena). |
| **Ventana de contexto** | El "espacio" total de texto (medido en tokens) que el modelo puede leer de una vez en cada llamada. |
| **Token** | La unidad en que el modelo cuenta texto (≈ ¾ de palabra). Tú pagas por tokens de entrada y de salida. |
| **CAG** | *Cache-Augmented Generation*: meter **todo** el conocimiento relevante en el prompt, precargado, sin búsqueda. |
| **RAG** | *Retrieval-Augmented Generation*: **buscar** los documentos relevantes en cada pregunta y solo esos van al prompt. |
| **Prompt** | El texto completo que se envía al modelo (instrucciones + contexto + pregunta). |
| **System prompt** | El bloque de instrucciones que define rol y comportamiento del modelo para toda la interacción. |
| **Embedding** | Convertir texto en un vector de números que captura su significado (lo usa RAG, no CAG). |
| **Base de datos vectorial** | Almacén que guarda embeddings y permite buscar los más parecidos (infraestructura de RAG). |
| **Latencia** | Cuánto tarda en responder. |

---

## La idea en una página

Un LLM aprende en su entrenamiento y luego tiene **fecha de corte**: no conoce nada posterior ni los datos privados de tu empresa. Si le preguntas cuánto costó el último proyecto de tu equipo, no puede saberlo. La solución es inyectarle conocimiento externo **en la inferencia**. Hay dos estrategias:

| | RAG ("ir a buscar") | CAG ("llevarlo todo encima") |
|---|---|---|
| Qué hace | Busca en una BD los docs relevantes y solo esos van al prompt | Precarga **todo** el conocimiento en el prompt, sin búsqueda |
| Analogía del consultor | Un armario con cientos de presupuestos; por cada cliente va, busca los parecidos y los lleva a la mesa | Cinco o diez presupuestos recientes, ya sobre la mesa, a la vista |
| Riesgo | Elegir mal, tardar, dejarse uno fuera | Si necesitas cientos, no caben en la mesa |
| Gana cuando | Los datos son enormes o cambian a cada minuto | El conocimiento **cabe** en la ventana y es estático |

> Ninguna es mejor en abstracto. Esta sesión construye el estimador en su versión **más simple posible** —CAG puro, sin BD, sin búsqueda— porque los datos de referencia son pocos y caben. Es la primera fase natural de un producto con IA: **CAG (Mód. 2) → RAG (Mód. 3-4) → Agentes (Mód. 5).**

El recorrido del código del estimador está en [`../codigo-explicado.md`](../codigo-explicado.md).

---

# Parte 1 — ¿Qué es CAG?

## El punto de partida

El conocimiento del LLM se fija en el entrenamiento y tiene fecha de corte: no incluye datos privados ni nada posterior. RAG y CAG persiguen lo mismo —que el modelo disponga de información relevante— pero de formas fundamentalmente distintas.

## RAG: ir a buscar

Cuando un usuario pregunta, el sistema busca primero los documentos más relevantes en una BD (normalmente vectorial), los recupera y los mete en el prompt junto a la pregunta.

```
Pregunta → Búsqueda en BD vectorial → Fragmentos más relevantes
        → Prompt (instrucciones + fragmentos + pregunta) → LLM → Respuesta
```

Es potente y escalable (millones de documentos), pero esa potencia cuesta: necesita **infraestructura de búsqueda** (BD vectorial, modelos de embeddings, pipeline de indexación), introduce **latencia** en cada consulta (el tiempo de *retrieval*), y los **errores de selección** degradan la respuesta (si recupera lo irrelevante o se deja lo bueno fuera).

> **Retrieval** = el paso de buscar y recuperar los documentos relevantes antes de llamar al modelo.

## CAG: llevar todo encima

Radicalmente más simple. En lugar de buscar en cada consulta, **precarga todo el conocimiento en la ventana de contexto**. No hay búsqueda en tiempo real, ni BD vectorial, ni pipeline de retrieval; todo el contexto viaja en cada llamada.

```
Todo el conocimiento (precargado) + Pregunta
        → Prompt (instrucciones + TODO el conocimiento + pregunta) → LLM → Respuesta
```

Al eliminar el retrieval, CAG elimina de golpe **tres problemas** de RAG: la latencia de búsqueda, los errores de selección y la complejidad arquitectónica.

## Cuándo usar CAG (y cuándo no)

No es preferencia, sino características de tus datos.

**CAG es correcto cuando:**
- **El conocimiento es acotado y cabe en la ventana.** Para un modelo de 128K tokens, eso son ~200-250 páginas; con ventanas de 1M+, mucho más.
- **Los datos son estáticos** — no cambian cada hora: documentación, políticas, FAQs, manuales o, en nuestro caso, un conjunto acotado de estimaciones históricas.
- **Necesitas latencia mínima** — sin retrieval, responde tan rápido como el modelo genere.
- **Quieres simplicidad** — menos componentes = menos fallos, menos mantenimiento, *time-to-market* más rápido. Sin BD vectorial, sin embeddings, sin indexación.

**CAG NO es correcto cuando:**
- **El conocimiento es grande y crece** — miles de documentos que no caben, o datos en tiempo real (noticias, inventario, métricas).
- **Necesitas precisión en la selección** — cuando mezclar datos irrelevantes con relevantes confunde al modelo (*context distraction*).
- **El coste por token es crítico** — cada llamada CAG envía todo el contexto: más tokens de entrada y más coste por llamada. Con alto volumen, el coste escala rápido.

## Los componentes de una arquitectura CAG

1. **Fuente de conocimiento.** Los datos que el modelo necesita (en el proyecto, presupuestos históricos). Deben estar **listos para inyectar**: limpios, bien formateados, con lo relevante destacado. Un JSON crudo de 50 campos no es buen contexto; un resumen estructurado sí.
2. **Capa de preprocesamiento.** Transforma los datos antes de inyectarlos: selecciona campos relevantes, los formatea legible, anonimiza lo sensible, agrega lo disperso. Aquí se deciden cosas críticas (qué incluir, qué omitir, en qué formato) que impactan en calidad y consumo de tokens.
3. **Constructor de prompts.** Estructura típica:

   ```
   ┌──────────────────────────────┐
   │ SYSTEM PROMPT (rol + instrucciones) │
   ├──────────────────────────────┤
   │ CONTEXTO / CONOCIMIENTO (datos precargados) │
   ├──────────────────────────────┤
   │ MENSAJE DEL USUARIO (consulta/transcripción) │
   └──────────────────────────────┘
   ```
   System prompt vago → respuestas vagas; contexto desordenado → respuestas desordenadas.
4. **Servicio de llamada al LLM.** Gestiona la API del proveedor (OpenAI, Anthropic...): claves seguras, errores y reintentos, límites de tasa, y extracción de lo relevante (contenido, tokens, metadatos).
5. **Postprocesamiento.** La respuesta es texto. Según el caso: parsear a JSON, validar restricciones, extraer datos, verificar coherencia. Ejemplo: una estimación que diga "10 horas de frontend" con coste de 50.000 € hay que detectarla y corregirla.

## CAG en nuestro proyecto (primera iteración)

1. **Fuente:** estimaciones históricas como datos estáticos en el código.
2. **Preprocesamiento:** formatear cada ejemplo para que sea legible y útil como referencia.
3. **Prompt:** system prompt que define al modelo como experto en estimación + estimaciones de ejemplo como contexto + transcripción de la reunión a estimar.
4. **Llamada al LLM:** envío del prompt completo y recepción de la estimación.
5. **Postprocesamiento:** extracción de la estimación utilizable (tareas, horas, costes).

> Es la versión más simple posible de un sistema con IA que resuelve un problema real. Sin BD, sin embeddings, sin retrieval. Y funciona porque los datos caben. Empezar con CAG permite tener algo funcional rápido y centrarse en lo que importa: calidad del prompt, estructura de los datos y diseño de la respuesta.

## La ventana de contexto: el recurso más valioso en CAG

Si CAG es meter todo el conocimiento en la ventana, **su tamaño es el factor limitante**. Dos cosas que todo dev debe saber:

- **El tamaño anunciado ≠ el útil.** Un modelo de 128K no te da 128K para tu conocimiento: parte se va en system prompt, parte en la respuesta (tokens de salida) y parte en overhead interno. En la práctica, lo útil suele ser el **60-80 %**.
- **Más contexto ≠ mejor respuesta.** Los modelos **pierden atención al crecer el contexto**: el principio y el final reciben más atención que el medio. Es el efecto **"lost in the middle"**. A partir de cierto punto, añadir contexto degrada en vez de mejorar.

## De CAG a RAG: el camino natural

CAG y RAG no son excluyentes, sino **fases de madurez de un mismo sistema**. Muchos productos empiezan con CAG (la forma más rápida de validar); cuando los datos crecen o sube la necesidad de precisión, se añade la capa de retrieval y se evoluciona a RAG.

```
Mód. 2: CAG (contexto estático, sin persistencia, todo en el prompt)
   ▼
Mód. 3-4: RAG (BD vectorial, embeddings, búsqueda semántica)
   ▼
Mód. 5: Agentes (orquestación, razonamiento multi-paso, tools)
```

> Cada fase añade capacidad **y** complejidad. Entender CAG a fondo es imprescindible para apreciar qué aporta RAG y cuándo el salto de complejidad está justificado.

---

# Parte 2 — El paper: *Don't do RAG when CAG is all you need*

El **paper fundacional de CAG**, de **Chan et al.**, presentado en la **ACM Web Conference 2025**. Propone precargar todo el conocimiento en la ventana del LLM mediante **KV-cache precomputado**, eliminando el retrieval en tiempo real y reduciendo latencia y complejidad.

> **KV-cache** = al procesar texto, el modelo calcula unas representaciones intermedias (las "claves y valores" de la atención) que normalmente recalcula en cada llamada. El KV-cache las **guarda precomputadas** para el conocimiento fijo, así el modelo no reprocesa todo el contexto desde cero cada vez. Es lo que hace que precargar mucho conocimiento estático salga barato en latencia.

Incluye benchmarks en **SQuAD** y **HotPotQA** donde CAG **iguala o supera a RAG en precisión**, con tiempos de generación mucho menores. Es la base teórica del proyecto, sobre todo donde el conocimiento es acotado y cabe entero en contexto.

- Paper: https://arxiv.org/html/2412.15605v1
- Referencia complementaria (estrategias de contexto): https://blog.logrocket.com/llm-context-problem-strategies-2026

---

# Parte 3 — Arquitectura escalable en proyectos de IA generativa

## ¿Por qué FastAPI?

Las apps con LLMs tienen un **perfil de ejecución distinto** al de las web tradicionales: una petición CRUD tarda milisegundos; una llamada a un LLM, **entre 2 y 30 segundos**.

> **CRUD** = las operaciones básicas de datos (Create/Read/Update/Delete), el grueso de una web tradicional, muy rápidas.
> **Síncrono / threads** = modelo donde cada petición ocupa un hilo de ejecución completo hasta terminar (Rails+Puma, Django+Gunicorn WSGI).

En un framework síncrono, cada petición al LLM **bloquea un thread** todo ese tiempo; bajo carga, los workers se agotan esperando sin hacer nada útil. FastAPI está sobre **ASGI** y soporta `async/await` nativo: cuando una petición espera al LLM, el *event loop* libera ese hilo para atender otras.

> **ASGI** = el estándar Python para servidores web asíncronos (sucesor de WSGI).
> **async/await** = sintaxis para que el código suelte el hilo mientras espera (I/O) y atienda otras tareas entretanto.
> **I/O-bound** = trabajo que pasa el tiempo *esperando* (red, disco), no calculando — justo el perfil de llamar a un LLM.

Un solo proceso FastAPI maneja **decenas de peticiones concurrentes** con la memoria que un síncrono dedicaría a una. No es la única opción, pero su modelo de concurrencia encaja con la realidad de las cargas con IA: muchas operaciones **I/O-bound de larga duración**.

## El problema del archivo único

FastAPI levanta un servidor en cinco líneas. Bien para prototipar, mal cuando el proyecto crece:

```python
# main.py — todo en un archivo
app = FastAPI()
client = OpenAI()

@app.post("/estimate")
async def estimate(transcription: str):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Eres un estimador de software..."},
            {"role": "user", "content": transcription}
        ]
    )
    return {"estimation": response.choices[0].message.content}
```

Funciona, pero mezcla todo: configuración del cliente, lógica de negocio (prompt, qué contexto inyectar), endpoint HTTP y estructura de respuesta. Es el problema de los *fat controllers* de Rails. La solución es familiar: **separación de responsabilidades**.

## Estructura por responsabilidades

```
estimador-cag/
├── app/
│   ├── main.py            ← Punto de entrada
│   ├── config.py          ← Configuración centralizada
│   ├── routers/           ← Endpoints HTTP (transporte)
│   │   └── estimations.py
│   ├── services/          ← Lógica de negocio (capa inteligente)
│   │   └── llm_service.py
│   ├── schemas/           ← Contratos de datos (request/response)
│   │   └── estimation.py
│   └── context/           ← Datos de referencia para CAG
│       └── examples.py
├── tests/
├── .env  /  .env.example  /  .gitignore  /  pyproject.toml
```

No es inventada para el curso: adapta patrones probados en producción a apps con LLM. Cada directorio tiene **una** responsabilidad.

## `config.py` — la capa de configuración

> **Pydantic `BaseSettings`** = patrón estándar que combina dos cosas: cargar variables de entorno **y** validar su tipo/formato.

```python
class Settings(BaseSettings):
    OPENAI_API_KEY: str
    LLM_PROVIDER: str = "openai"
    LLM_MODEL: str = "gpt-4o-mini"
    APP_ENV: str = "development"
    LOG_LEVEL: str = "DEBUG"

    class Config:
        env_file = ".env"

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

> **`@lru_cache`** = decorador que cachea el resultado: la configuración se carga **una sola vez** y se reutiliza (un singleton sin maquinaria de patrones).

Ventaja clave de validar en carga: si `OPENAI_API_KEY` no está, la app **falla al arrancar**, no en la primera petición del usuario. **Fallar rápido es una ventaja, no un problema.**

## `routers/` — la capa de transporte

Los routers son el equivalente a los *controllers* en MVC. Su única responsabilidad es la **comunicación HTTP**: recibir, validar la entrada, delegar en servicios y formatear la respuesta.

```python
# routers/estimations.py
router = APIRouter(prefix="/api/v1", tags=["estimations"])

@router.post("/estimate", response_model=EstimationResponse)
async def estimate(request: EstimationRequest):
    result = await generate_estimation(request.transcription)
    return result
```

Observa lo que el endpoint **no** hace: no construye prompts, no llama a OpenAI, no gestiona errores del LLM, no formatea la estimación. Solo recibe, delega y devuelve. **Endpoints finos; la lógica vive en los servicios.**

## `services/` — la capa de negocio

Aquí vive la inteligencia: construcción del prompt, inyección de contexto, llamada al modelo y procesamiento de la respuesta.

```python
# services/llm_service.py
settings = get_settings()
client = OpenAI(api_key=settings.OPENAI_API_KEY)

def build_system_prompt() -> str:
    examples_text = format_examples(ESTIMATION_EXAMPLES)
    return f"""Eres un experto en estimación de proyectos de software.
Utiliza los siguientes presupuestos históricos como referencia:
{examples_text}
Genera una estimación detallada para el proyecto descrito."""

async def generate_estimation(transcription: str) -> dict:
    system_prompt = build_system_prompt()
    response = client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": transcription}
        ]
    )
    return {
        "estimation": response.choices[0].message.content,
        "model": settings.LLM_MODEL,
        "provider": settings.LLM_PROVIDER,
    }
```

Consecuencia práctica: puedes **testear la lógica de prompts sin HTTP** y **testear endpoints sin llamar al LLM real** (con mocks). Al crecer, esta capa se subdividirá (`prompt_builder.py`, `llm_client.py`, `postprocessor.py`), pero en la primera iteración un solo archivo basta.

## `schemas/` — los contratos de datos

Pydantic no es solo validación: es el **sistema de tipos de tu API**. Cada schema es un contrato explícito.

```python
# schemas/estimation.py
class EstimationRequest(BaseModel):
    transcription: str = Field(..., min_length=50,
        description="Transcripción de la reunión con el cliente")

class EstimationResponse(BaseModel):
    estimation: str
    model: str
    provider: str
```

Hacen tres cosas automáticamente: **validan** (≥50 caracteres, evitando llamadas inútiles al LLM), generan **documentación interactiva en Swagger**, y **serializan** la respuesta al JSON correcto. Equivalente a los serializers de Rails o los DTOs de NestJS. Ventaja: el contrato está **en código**, no en un README que nadie actualiza.

## `context/` — los datos de referencia

Esta capa es **específica de CAG**. Contiene los datos que se inyectan en cada llamada: los ejemplos de estimaciones históricas.

```python
# context/examples.py
ESTIMATION_EXAMPLES = [
    {
        "meeting_summary": "El cliente necesita una plataforma web de...",
        "estimation": "## Estimación: Plataforma de Gestión de Inventario..."
    },
    # ... más ejemplos
]
```

En esta iteración los datos son **estáticos** —definidos en el código—. Es deliberado: permite iterar sobre la calidad de los ejemplos sin tocar infraestructura. Al evolucionar a RAG, esta capa será un servicio de búsqueda semántica sobre una BD vectorial.

> Tener esta capa separada desde el principio da un **punto de sustitución limpio**: el servicio LLM no sabe ni le importa si los ejemplos vienen de un diccionario en memoria o de una query a pgvector. Solo recibe datos formateados.

## `main.py` — el punto de entrada

El pegamento: crea la instancia FastAPI, registra routers, configura middleware.

```python
# main.py
app = FastAPI(
    title="Estimador CAG",
    description="Sistema de estimación de software con arquitectura CAG",
    version="0.1.0"
)
app.include_router(estimations.router)

@app.get("/health")
async def health():
    return {"status": "healthy"}
```

Que `main.py` sea breve es señal de buena organización. Si crece, probablemente estés poniendo lógica donde no debería.

## El flujo completo de una petición

```
Cliente (curl, Swagger, frontend)
  ▼ routers/estimations.py     ← Valida el request con Pydantic
  ▼ services/llm_service.py    ← Construye el prompt con contexto
  ▼ API del LLM (OpenAI/Anthropic)
  ▼ services/llm_service.py    ← Procesa la respuesta
  ▼ routers/estimations.py     ← Serializa el response con el schema
  ▼ Cliente (JSON response)
```

Cada capa hace una cosa: si falla el LLM, el error se gestiona en el servicio, no en el router; si cambia el formato de respuesta, se toca el schema; si cambia la estrategia de prompt, se toca el servicio.

## Convenciones que importan

- **Dependencias con `uv`** (equivalente a Bundler o pnpm/yarn). El `pyproject.toml` declara dependencias y `uv` las resuelve:
  ```bash
  uv sync                              # Instalar
  uv add httpx                         # Añadir dependencia
  uv run uvicorn app.main:app --reload # Ejecutar
  ```
- **Variables de entorno y seguridad.** Las claves API **nunca** en el código: van en un `.env` (en `.gitignore`) y se acceden vía la capa de configuración. El `.env.example` documenta qué variables hacen falta sin exponer valores.
- **Versionado de API.** El prefijo `/api/v1` no es decorativo: permite evolucionar (añadir `/api/v2` con nuevo contrato) sin romper a los clientes de `/api/v1`.

## Cómo evoluciona esta estructura

Crece de forma natural sin reescribirse:

| Sesión 02 (CAG) | Mód. 3-4 (RAG) añaden | Mód. 5 (Agentes) añaden |
|---|---|---|
| `routers/estimations.py` | `routers/ingestion.py` | más routers |
| `services/llm_service.py` | `services/embedding.py`, `retrieval.py`, `ingestion.py` | más servicios |
| `schemas/estimation.py` | `schemas/document.py` | — |
| `context/examples.py` | `models/` (base, document, chunk), `db/session.py` | — |

> Cada módulo **añade archivos sin tocar la estructura fundamental.** Routers finos, servicios con la lógica, schemas con los contratos. Cambia la cantidad de servicios y su complejidad interna, no la arquitectura.

---

# Parte 4 — Gestión efectiva del contexto

## El contexto como recurso finito

En CAG, la ventana es tu **recurso más valioso y tu límite más duro**. Todo cabe ahí: instrucciones, conocimiento, consulta y el espacio que el modelo necesita para responder. No hay BD vectorial de respaldo: **lo que no está en el contexto, no existe para el modelo.** Gestionar este recurso con criterio separa un CAG útil de uno que produce texto genérico.

## Anatomía de la ventana

```
VENTANA DE CONTEXTO (ej: 128K tokens total)
  ┌────────────────────────────────────────────┐
  │ System prompt: instrucciones + rol  (~500-1.500 tok) │
  │ Contexto inyectado: estimaciones    (~2.000-40.000)  │
  │ Mensaje del usuario: transcripción  (~500-5.000)     │
  │ Respuesta del modelo: estimación    (~1.000-3.000)   │
  │ Espacio no utilizado (el "desperdicio")              │
  └────────────────────────────────────────────┘
```

La suma **no puede exceder** el tamaño de la ventana. Si lo hace, la llamada falla o el sistema **trunca contenido en silencio** (resultados impredecibles). Matiz sutil: aunque todo quepa, no garantiza buen uso — la atención se degrada de forma **no lineal** ("lost in the middle").

## Presupuesto de tokens: planifica antes de codificar

Para el estimador con `gpt-4o-mini` (128K) o `claude-haiku-4-5` (200K), cálculo orientativo:

| Bloque | Tokens | % del total |
|---|---|---|
| System prompt (instrucciones + formato) | ~1.000 | 1 % |
| Contexto de referencia (estimaciones) | ~5.000-30.000 | 4-23 % |
| Transcripción del usuario | ~1.000-5.000 | 1-4 % |
| Respuesta del modelo | ~1.500-3.000 | 1-2 % |
| Margen de seguridad | ~5.000 | 4 % |
| **Total utilizado** | **~13.500-44.000** | **11-34 %** |

Dos conclusiones. La evidente: en CAG **hay espacio de sobra** (5-10 estimaciones no se acercan al límite), y eso es lo que hace viable CAG aquí. La menos obvia pero más importante:

> **Que tengas espacio no significa que debas llenarlo.** Cada token extra tiene coste **económico** (pagas entrada) y **atencional** (el modelo procesa más para hallar lo relevante). El objetivo no es el máximo posible, sino **el mínimo necesario con la máxima calidad.**

## Qué incluir en el contexto (y qué no)

Decidir qué entra es una **decisión de diseño**, no técnica.

**Mejora la respuesta:**
- **Ejemplos completos con desglose.** No basta "un e-commerce costó 200 horas": el modelo necesita ver **qué tareas, cuántas horas, qué tecnologías, qué equipo**. El desglose es lo que le permite generar un desglose coherente.
- **Patrones de precios y dedicación.** Si un día de backend cuesta 500 € y uno de UX 400 €, el modelo necesita esa referencia para no inventar cifras.
- **Estructura y formato del output esperado.** Un ejemplo del resultado final es más efectivo que describir el formato en texto.

**Degrada la respuesta:**
- **Detalle que no aporta al patrón.** El historial completo de comunicaciones con el cliente es **ruido** para estimar.
- **Información contradictoria.** Mezclar estimaciones de épocas muy distintas (precios, tecnologías obsoletas) genera patrones incompatibles. Mejor pocas relevantes y actuales que muchas heterogéneas.
- **Contexto redundante.** Tres e-commerce muy parecidos → la 2ª y la 3ª aportan **rendimientos decrecientes**. Mejor uno de e-commerce, uno de SaaS y uno interno: más diversidad, menos tokens.

## Cómo formatear el contexto

El formato afecta a cómo el modelo interpreta el texto. Tres opciones:

| Formato | Cuándo | Tokens |
|---|---|---|
| **Texto plano estructurado** | Datos descriptivos/narrativos | El **más eficiente** |
| **JSON** | Relaciones jerárquicas o si el output esperado es JSON | **Consume más** (llaves, comillas, indentación) |
| **Markdown** | Punto intermedio: jerarquía clara con headers | Más eficiente que JSON — **es el formato por defecto del proyecto** |

Ejemplo de texto plano estructurado:
```
--- Estimación de referencia 1 ---
Proyecto: Plataforma de gestión de inventario
Tareas:
Diseño UI/UX: 40 horas a 400 EUR/hora → 16.000 EUR
Backend API REST: 60 horas a 500 EUR/hora → 30.000 EUR
Total: 120 horas, 56.000 EUR
Equipo: 2 developers full-stack, 1 diseñador UX (part-time)
Duración: 6-8 semanas
```

> **Regla práctica: usa el formato que más se parezca al output que esperas.** Si quieres estimaciones en Markdown con secciones y tablas, da los ejemplos en Markdown con secciones y tablas. El modelo **replica los patrones que ve.**

**Separadores y delimitadores.** Con múltiples ejemplos hay que marcar dónde empieza y acaba cada uno; sin ellos, el modelo mezcla información:
```
===== ESTIMACIÓN DE REFERENCIA 1 =====
[contenido]
===== ESTIMACIÓN DE REFERENCIA 2 =====
[contenido]
===== FIN DE ESTIMACIONES DE REFERENCIA =====
```
Cumplen doble función: ayudan al modelo a entender la estructura y a ti a **debuggear** cuando la respuesta no es la esperada.

## La posición importa

El efecto "lost in the middle" implica: lo más importante va **al principio o al final**, nunca enterrado en el medio. Orden deliberado en el estimador:

```
1. System prompt con instrucciones claras        ← PRINCIPIO (máxima atención)
2. Formato esperado del output
3. Estimaciones de referencia (las más relevantes primero)
4. [... más estimaciones ...]
5. Restricciones y reglas específicas             ← CERCA DEL FINAL
6. Transcripción de la reunión (mensaje usuario)  ← FINAL (máxima atención)
```

Instrucciones al principio (definen el comportamiento de toda la interacción); transcripción al final (la consulta directa); estimaciones en el medio **ordenadas por relevancia**; restricciones justo antes de la transcripción, donde reciben atención. No es arbitrario: es ingeniería basada en cómo los modelos distribuyen su atención.

## El system prompt: dirige todo

Define **quién es el modelo y cómo se comporta**, y en CAG también **cómo interpretar el contexto de referencia**. Uno débil ("Eres un asistente que ayuda con estimaciones de software") es demasiado vago: el modelo no sabe formato, detalle ni para qué están las referencias.

Un system prompt efectivo define **cuatro dimensiones**:
1. **Rol y expertise** — qué tipo de experto y con qué experiencia. Más específico = respuesta más calibrada.
2. **Tarea concreta** — qué hacer exactamente: analizar una transcripción y generar una estimación.
3. **Uso del contexto** — cómo interpretar las estimaciones históricas (¿ejemplos de formato? ¿calibración de precios? ¿proyectos similares?). El modelo necesita saber para qué están.
4. **Formato del output** — estructura, campos obligatorios, unidades, detalle. Si no lo especificas, el modelo decide por ti, y no siempre bien.

Ejemplo efectivo:
```
Eres un consultor senior de software con 15 años de experiencia en estimación.
Analiza transcripciones de reuniones con clientes y genera estimaciones detalladas.

A continuación, estimaciones de proyectos anteriores. Úsalas como referencia para
calibrar: precios por hora, granularidad del desglose y estructura deben ser
consistentes con estos ejemplos.

Tu estimación debe incluir:
1. Resumen del proyecto (2-3 frases)
2. Desglose de tareas con horas y coste
3. Equipo recomendado
4. Duración total estimada
5. Riesgos o supuestos clave

Usa EUR. Redondea las horas a múltiplos de 5.
```

> **La calidad del system prompt es posiblemente el factor que más impacta en el output, y sin embargo es al que menos tiempo se le dedica.**

## Preprocesamiento: la capa invisible

Entre los datos crudos y el contexto hay una transformación (en FastAPI vive en el servicio: la función que toma `context/examples.py` y lo convierte en texto para el prompt). Operaciones típicas:

- **Selección de campos.** Un presupuesto puede tener 50 campos. El modelo no necesita el ID interno, la fecha de creación, el email del comercial ni las condiciones de pago para estimar. Incluirlos consume tokens sin valor.
- **Normalización.** Si uno usa "días" y otro "horas", normaliza a una unidad común. El modelo maneja inconsistencias, pero cada una mete probabilidad de error.
- **Campos derivados.** Si hay `quantity: 15` y `unit_price: 500` pero no `total`, calcúlalo y añádelo — los LLMs no son fiables en aritmética.
- **Anonimización.** Nombres, emails y datos sensibles se eliminan o generalizan antes. El modelo no necesita "Empresa X", necesita "plataforma de e-commerce con 50K usuarios mensuales".

> Parecen menores, pero su efecto acumulativo es sustancial. Un contexto limpio, consistente y sin ruido produce respuestas mucho mejores que un volcado directo de datos crudos.

## Cuántos ejemplos incluir

No "todos los que quepan", sino "los que aporten sin generar ruido":
- **2-3 ejemplos:** suficientes para que el modelo entienda formato, escala de precios y nivel de desglose. **Mínimo viable.**
- **5-7 ejemplos: el punto dulce.** Diversidad de tipos (web, móvil, API, integración) para calibrar bien sin inundar.
- **>10 ejemplos:** rendimientos decrecientes. El octavo e-commerce no aporta nada nuevo y diluye la atención.

> Cuando 10 ejemplos no bastan y necesitas cientos, es exactamente el momento en que **la migración a RAG está justificada**: un servicio de búsqueda semántica selecciona los 5-7 más relevantes de entre cientos — precisión de selección + eficiencia de contexto acotado.

## Iteración sobre el contexto

Ventaja poco mencionada de CAG: la **velocidad de iteración**. Como los datos viven en el código, cambiar un ejemplo, reformatear o ajustar el system prompt es **inmediato**. Sin re-indexar BD, sin recalcular embeddings, sin pipeline de ingesta.

```
1. Ejecutar una estimación de prueba
2. Evaluar la calidad
3. Identificar el problema:
   ¿Formato inadecuado?       → Ajustar system prompt
   ¿Precios descalibrados?    → Mejorar ejemplos de referencia
   ¿Desglose genérico?        → Añadir detalle a los ejemplos
   ¿Info irrelevante?         → Añadir restricciones
4. Modificar el contexto → 5. Volver al paso 1
```

Cada iteración son segundos (`--reload` reinicia solo). Esa velocidad se pierde en parte al migrar a RAG (los cambios exigen re-vectorización). Razón para **explotar la fase CAG al máximo**: invertir ahora en el formato óptimo y el mejor system prompt ahorra esfuerzo después.

## Errores comunes en la gestión de contexto

- **Contexto demasiado genérico.** Ejemplos muy distintos entre sí y del proyecto: el modelo no tiene patrón claro y da una media difusa.
- **Instrucciones contradictorias.** Si dices "sé conciso" pero los ejemplos son extensos, hay señales opuestas. **Los ejemplos suelen ganar** (el modelo imita lo que ve): alinea instrucciones y ejemplos.
- **Sin formato de output.** Cada llamada produce una estructura distinta. En producción, la consistencia de formato es tan importante como el contenido.
- **Volcado sin curación.** Pegar un JSON de 200 líneas es la forma más segura de obtener resultados pobres. La curación es responsabilidad del dev, no del modelo.
- **Ignorar el coste acumulativo.** 10.000 tokens de contexto × 1.000 llamadas/día = **10 millones de tokens de entrada al día solo en contexto.** El coste se multiplica por el volumen.

---

# Parte 5 — Arquitectura de conversaciones con modelos

## La interfaz real: un array de mensajes

Cuando usas ChatGPT o Claude, parece una conversación fluida donde el modelo "recuerda". Es una **ilusión de la interfaz**. Por debajo, cada vez que envías un mensaje, la app empaqueta **toda la conversación completa** en un único array de objetos JSON y lo manda al modelo.

> **El modelo no tiene memoria entre llamadas.** Lee toda la conversación de principio a fin, responde y se olvida de todo. En la siguiente llamada recibe otra vez todo el historial y lo procesa como si fuera la primera vez.

```python
messages = [
    {"role": "system", "content": "Instrucciones para el modelo..."},
    {"role": "user", "content": "Primera pregunta del usuario"},
    {"role": "assistant", "content": "Primera respuesta del modelo"},
    {"role": "user", "content": "Segunda pregunta del usuario"},
    {"role": "assistant", "content": "Segunda respuesta del modelo"},
    {"role": "user", "content": "Tercera pregunta del usuario"},
    # → el modelo genera la respuesta a esta última pregunta
]
```

Todo lo que el modelo sabe está en este array. **Si no está aquí, no existe.**

## Los tres roles

> **`role`** = etiqueta de cada mensaje que le dice al modelo quién lo dice y cómo interpretarlo.

- **`system` — las reglas del juego.** Comportamiento global para toda la conversación. La única parte que el modelo lee como **instrucciones de configuración**, no como contenido. Se envía en **cada llamada**: 20 turnos = el system prompt 20 veces. Una razón más para que sea conciso — cada palabra de más se paga multiplicada.
- **`user` — lo que pide el humano.** Las entradas del usuario. En el estimador, el primer `user` contiene la transcripción.
- **`assistant` — lo que dijo el modelo.** Las respuestas previas. Lo contraintuitivo: **tú eres responsable de guardar las respuestas del modelo e incluirlas en las siguientes llamadas**; el modelo no lo hace. Si el usuario pide "ajusta las horas de diseño a 50", el modelo necesita ver su propia respuesta anterior en el array para saber qué ajusta.

## Single-turn vs multi-turn

| | Single-turn (transaccional) | Multi-turn (conversacional) |
|---|---|---|
| Qué es | Una pregunta, una respuesta, fin | Conversación donde cada turno construye sobre los anteriores |
| Historial | No hay que gestionarlo | Hay que guardarlo y reenviarlo |
| Ventaja | Simplicidad, sin estado | Experiencia rica: el usuario refina en diálogo |
| Desventaja | No puedes iterar sin repetir todo el contexto | **Coste acumulativo**: cada turno incluye todos los anteriores |

```python
# Single-turn: no hay historial
messages = [
    {"role": "system", "content": system_prompt_con_contexto},
    {"role": "user", "content": transcripcion_de_reunion}
]
```

## Gestión del historial en memoria

En multi-turn hace falta almacenar el historial. En CAG, lo más directo es **mantenerlo en memoria** (una lista de Python que crece con cada turno):

```python
class ConversationManager:
    def __init__(self, system_prompt: str):
        self.messages = [{"role": "system", "content": system_prompt}]

    def add_user_message(self, content: str):
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str):
        self.messages.append({"role": "assistant", "content": content})

    def get_messages(self) -> list:
        return self.messages.copy()
```

Intencionadamente simple: sin persistencia ni BD. Si el servidor se reinicia, las conversaciones se pierden — aceptable en esta fase (la persistencia es de sesiones posteriores). Lo que **sí** hay que gestionar desde el principio: qué pasa cuando la conversación crece demasiado.

## El problema del crecimiento

Cada turno añade 1.000-4.000 tokens; con un system prompt que ya lleva las estimaciones (5.000-30.000), la ventana se llena:

```
System prompt con contexto CAG:   15.000 tokens
Turnos 1-5 (user + assistant):    ~13.000 tokens
Espacio para respuesta turno 6:    3.000 tokens
──────────────────────────────────────────
Total:                            ~31.000 tokens
```

31.000 está lejos de 128K, pero el crecimiento es real y en conversaciones largas es problema — no solo de espacio, también de **calidad** (más tokens = más coste y menos atención efectiva). Tres estrategias:

**1. Ventana deslizante.** La más simple: mantienes los últimos N turnos y descartas los antiguos (el system prompt siempre se conserva). Predecible, pero si algo importante se dijo en el turno 1 y vas por el 15, se pierde.
```python
def get_messages_windowed(self, max_turns: int = 10) -> list:
    system = [self.messages[0]]      # Siempre conservar el system prompt
    history = self.messages[1:]
    if len(history) > max_turns * 2:
        history = history[-(max_turns * 2):]
    return system + history
```

**2. Resumen acumulativo (compactación).** En vez de descartar, **resumes** los turnos antiguos en un mensaje compacto al principio (generado por el propio LLM). **Ventaja:** conserva lo esencial de toda la conversación. **Desventaja:** el resumen es una operación extra (tokens + tiempo) y su calidad depende de la instrucción.
```
[system prompt]
[resumen turnos 1-8: "El usuario pidió una estimación para una plataforma de
 reservas. Equipo de 3, duración 8 semanas. Se ajustaron horas de diseño 40→60."]
[turno 9: user] [turno 9: assistant] [turno 10: user]
```

**3. Híbrida con priorización.** Ventana deslizante + **marcado de turnos "ancla"** (donde se definió el alcance o se tomó una decisión clave) que nunca se descartan; los intermedios sí. La más sofisticada y la que mejor funciona en producción, pero requiere criterio para decidir qué es "ancla". Para la fase actual, la ventana deslizante basta.
```
[system prompt]
[turno 1: definición del proyecto — ANCLA]
[turno 5: decisión sobre equipo — ANCLA]
[turnos 8-10: últimos turnos — ventana deslizante]
```

## El patrón request-response en la práctica

```python
# services/llm_service.py
async def generate_estimation(transcription, conversation_history=None) -> dict:
    system_prompt = build_system_prompt()  # Incluye contexto CAG

    if conversation_history:  # Multi-turn
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": transcription})
    else:  # Single-turn
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": transcription}
        ]

    response = client.chat.completions.create(model=settings.LLM_MODEL, messages=messages)
    return {
        "estimation": response.choices[0].message.content,
        "model": settings.LLM_MODEL,
        "usage": {
            "input_tokens": response.usage.prompt_tokens,
            "output_tokens": response.usage.completion_tokens
        }
    }
```

El historial es **opcional**: vacío → single-turn; con turnos → multi-turn. El router decide el modo; el servicio no necesita saber por qué.

> Coherente con la estructura FastAPI: el servicio **no gestiona estado HTTP.** El estado conversacional vive fuera (router, cliente o middleware de sesión). El servicio solo recibe mensajes y devuelve respuestas.

## Diferencias entre proveedores que afectan a tu código

La estructura `messages` con roles es un **estándar de facto**, pero hay diferencias a contemplar si soportas más de uno:

| Aspecto | OpenAI | Anthropic |
|---|---|---|
| **System prompt** | Un mensaje más en el array | **Parámetro separado** (`system="..."`), fuera del array |
| **Campo de respuesta** | `response.choices[0].message.content` | `response.content[0].text` |

- **Alternancia estricta de roles.** Algunos modelos exigen alternar `user`/`assistant`. Dos `user` seguidos dan error. Si metes info entre turnos (p.ej. resultados de una herramienta), consolídala en un solo `user` o usa el rol `tool` que algunos proveedores soportan.
- **`max_tokens`.** Limita cuántos tokens genera el modelo. Si la estimación necesita desglose extenso y el límite es bajo, se corta abruptamente. Para estimaciones, **2.000-4.000 suele bastar**. **Configúralo explícitamente** (el valor por defecto varía por proveedor).

> Parecen menores con un proveedor, pero son fuente constante de bugs con varios sin una capa de abstracción. La **Sesión 03** verá patrones de diseño para wrappers de modelos que resuelven esto.

## De la conversación al producto

Decisiones de **diseño de producto**, no solo de implementación:
- **¿Conversacional o transaccional?** El estimador básico es **transaccional** (transcripción → estimación). Si añades refinar en diálogo, se vuelve **conversacional**. El transaccional no gestiona historial; el conversacional sí.
- **¿Quién controla el contexto?** En CAG el contexto se inyecta automáticamente y el usuario no lo ve. Podrías diseñar una variante donde el usuario **selecciona** qué presupuestos usar — eso mueve los datos de referencia del system prompt al mensaje del usuario.
- **¿Cómo comunicas los límites?** Si la conversación se alarga y empiezas a truncar, el modelo "olvida". Gestionar esa expectativa (avisar al acercarse al límite, ofrecer "reiniciar" con un resumen) es decisión de producto, no solo de ingeniería.

---

# Chuleta de una página

**CAG (Cache-Augmented Generation)**
- Precargar **todo** el conocimiento en la ventana. Sin búsqueda, sin BD vectorial, sin retrieval.
- Elimina 3 problemas de RAG: latencia de búsqueda, errores de selección, complejidad de infraestructura.
- A cambio: los datos deben **caber**, y cada llamada paga **todos** los tokens de contexto.
- **Usa CAG cuando:** datos acotados, estáticos, necesitas simplicidad y velocidad.
- **No uses CAG cuando:** datos masivos/dinámicos, o el coste por token a alto volumen es crítico.
- Es la **primera fase**: CAG (Mód. 2) → RAG (Mód. 3-4) → Agentes (Mód. 5).

**Ventana de contexto**
- Tamaño anunciado ≠ útil (cuenta con un **60-80 %** efectivo).
- "Lost in the middle": atención máxima al **principio y al final**, mínima en el medio.
- Presupuesta tokens **antes** de codificar. Menos es más: mínimo necesario, máxima calidad.

**Estructura del proyecto (FastAPI por capas)**
- `routers/` (transporte, **delgado**) → `services/` (lógica, LLM) → `schemas/` (contratos Pydantic) → `context/` (datos CAG, punto de sustitución CAG↔RAG).
- `config.py`: Pydantic `BaseSettings` + `@lru_cache`. Valida al **arrancar** (fail fast).
- FastAPI por su modelo **async** (llamadas LLM = I/O-bound largas). Claves en `.env` (nunca en código).

**Contexto efectivo**
- **Qué incluir:** ejemplos completos con desglose, patrones de precios, formato del output esperado.
- **Qué evitar:** datos irrelevantes, info contradictoria, ejemplos redundantes.
- **Formato:** Markdown por defecto (jerarquía clara, eficiente). Usa separadores `===== ... =====`.
- **Posición:** instrucciones al principio, restricciones cerca del final, consulta al final.
- **System prompt** = factor de mayor impacto. Define **rol + tarea + uso del contexto + formato**.
- **Preprocesamiento:** selección de campos, normalización, campos derivados, anonimización.
- **Nº de ejemplos:** 2-3 (mínimo viable), **5-7 (punto dulce)**, >10 (rendimientos decrecientes → señal de RAG).

**Conversaciones**
- Cada llamada es **stateless**: el modelo no recuerda nada; envías todo el array `messages` cada vez.
- Roles: `system` (config global) / `user` (humano) / `assistant` (respuestas previas — **tú** las guardas).
- **Single-turn** (transaccional, sin historial) vs **multi-turn** (conversacional, coste acumulativo).
- Gestión del historial: **ventana deslizante** (simple) / **resumen acumulativo** / **híbrida con anclas**.
- Proveedores difieren: system como mensaje (OpenAI) vs parámetro (Anthropic), alternancia de roles, `max_tokens`, campo de respuesta (`choices[0].message.content` vs `content[0].text`).

**Paper de referencia:** Chan et al., *Don't do RAG when CAG is all you need*, ACM Web Conference 2025 — https://arxiv.org/html/2412.15605v1
