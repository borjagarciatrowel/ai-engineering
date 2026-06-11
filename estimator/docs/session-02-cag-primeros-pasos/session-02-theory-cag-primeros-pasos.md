# Sesión 2 — Teoría: arquitectura CAG (Cache-Augmented Generation)

> Este documento resume **los cinco artículos teóricos** de la Sesión 2 en un único texto, en
> orden:
>
> 1. **¿Qué es CAG?** — la arquitectura, frente a RAG, sus componentes y cuándo usarla.
> 2. **El paper fundacional** — *Don't do RAG when CAG is all you need* (Chan et al., 2025).
> 3. **Arquitectura escalable** — por qué FastAPI y la estructura por capas del proyecto.
> 4. **Gestión efectiva del contexto** — presupuesto de tokens, formato, posición, system prompt.
> 5. **Arquitectura de conversaciones** — el array de mensajes, los tres roles y el historial.
>
> Cada parte empieza, cuando hace falta, con una **explicación para cualquiera** (sin tecnicismos)
> y luego entra en el detalle técnico. Al final hay una **chuleta de una página** con lo
> imprescindible. El recorrido del código del estimador está en
> [`../codigo-explicado.md`](../codigo-explicado.md).

---

## 0. La idea en una página (para cualquiera)

Un modelo de lenguaje (un LLM como GPT o Claude) aprende durante su entrenamiento y luego tiene
una **fecha de corte**: no conoce nada posterior, ni la información privada de tu empresa. Si le
preguntas cuánto costó el último proyecto que hizo tu equipo, no tiene forma de saberlo.

Para resolverlo, la industria alimenta al modelo con conocimiento externo **en el momento de la
pregunta**. Hay dos grandes estrategias:

- **RAG** (*Retrieval Augmented Generation*) — "ir a buscar": cuando llega una pregunta, el sistema
  busca en una base de datos los documentos más relevantes y solo esos se le pasan al modelo.
- **CAG** (*Cache Augmented Generation*) — "llevarlo todo encima": se le pasa al modelo **todo el
  conocimiento relevante de golpe**, precargado, sin búsqueda previa.

La analogía que usaremos toda la sesión: imagina un consultor que estima presupuestos. En **modo
RAG** tiene un armario con cientos de presupuestos antiguos; cuando llega un cliente va al armario,
busca los parecidos y se los lleva a la mesa (riesgo: equivocarse al elegir, tardar, dejarse uno
fuera). En **modo CAG** tiene cinco o diez presupuestos recientes ya sobre la mesa, a la vista
(riesgo distinto: si necesita cientos, no le caben en la mesa).

Ninguna es mejor en abstracto. CAG gana cuando el conocimiento **cabe** en la "mesa" del modelo (su
ventana de contexto) y no cambia cada minuto; RAG gana cuando los datos son enormes o cambian
constantemente. Esta sesión construye el estimador de software en su versión **más simple posible**
—CAG puro, sin base de datos, sin búsqueda— porque los datos de referencia son pocos y caben. Es la
primera fase natural de un producto con IA, y de aquí evolucionaremos a RAG (Módulos 3-4) y a
agentes (Módulo 5).

---

# PARTE 1 — ¿Qué es CAG? (Cache-Augmented Generation)

## 1.1 El punto de partida: cómo "sabe cosas" un LLM

El conocimiento de un LLM se fija durante su entrenamiento y tiene fecha de corte. No incluye datos
privados ni nada posterior. Para que responda con precisión sobre tu dominio, hay que **inyectarle
conocimiento externo en la inferencia**. RAG y CAG persiguen lo mismo —que el modelo disponga de
información relevante— pero lo hacen de formas fundamentalmente distintas.

## 1.2 RAG: la estrategia de ir a buscar

Cuando un usuario pregunta, el sistema busca primero los documentos más relevantes en una base de
datos (normalmente **vectorial**), los recupera y los incluye en el prompt junto a la pregunta. El
modelo responde basándose en esos documentos recuperados.

```
Pregunta del usuario
      │
      ▼
Búsqueda en base de datos vectorial
      │
      ▼
Selección de los fragmentos más relevantes
      │
      ▼
Construcción del prompt (instrucciones + fragmentos + pregunta)
      │
      ▼
Llamada al LLM
      │
      ▼
Respuesta generada
```

RAG es potente y escalable: puedes tener millones de documentos. Pero esa potencia cuesta:
necesitas **infraestructura de búsqueda** (base de datos vectorial, modelos de embeddings, pipeline
de indexación), introduce **latencia** en cada consulta (el tiempo de *retrieval*), y los **errores
de selección** degradan gravemente la respuesta: si recupera documentos irrelevantes o se deja los
buenos fuera, el modelo responde sobre contexto incorrecto o incompleto.

## 1.3 CAG: la estrategia de llevar todo encima

CAG es radicalmente más simple. En lugar de buscar en cada consulta, **precarga todo el
conocimiento necesario directamente en la ventana de contexto del modelo**. No hay búsqueda en
tiempo real, ni base de datos vectorial, ni pipeline de *retrieval*. Todo el contexto viaja en cada
llamada.

```
Todo el conocimiento relevante (precargado)
   +
Pregunta del usuario
      │
      ▼
Construcción del prompt (instrucciones + TODO el conocimiento + pregunta)
      │
      ▼
Llamada al LLM
      │
      ▼
Respuesta generada
```

Al eliminar el paso de *retrieval*, CAG elimina de un golpe **tres problemas** de RAG: la latencia
de búsqueda, los errores de selección de documentos y la complejidad arquitectónica del sistema.

## 1.4 La analogía del consultor

- **Modo RAG:** un armario con cientos de presupuestos. Por cada cliente vas, buscas los relevantes
  y te los llevas a la mesa. Riesgo: elegir mal las referencias, tardar buscando, o que se te
  escape uno muy relevante.
- **Modo CAG:** solo cinco o diez presupuestos recientes, bien organizados, todos a la vista
  mientras trabajas. No buscas nada. Riesgo distinto: si necesitas referenciar cientos, no caben en
  la mesa.

## 1.5 Cuándo usar CAG (y cuándo no)

No es cuestión de preferencia, sino de las características de tus datos y tu caso de uso.

**CAG es la opción correcta cuando:**

- **La base de conocimiento es acotada y manejable** — cabe en la ventana de contexto. Para un
  modelo de 128K tokens, eso son ~200-250 páginas de texto; con ventanas de 1M+ tokens, mucho más.
- **Los datos son relativamente estáticos** — no cambian cada hora: documentación de producto,
  políticas internas, FAQs, manuales, o —como en nuestro caso— un conjunto acotado de estimaciones
  históricas.
- **Necesitas latencia mínima** — sin paso de *retrieval*, CAG responde tan rápido como el modelo
  pueda generar.
- **Quieres simplicidad arquitectónica** — menos componentes = menos puntos de fallo, menos
  mantenimiento, *time-to-market* más rápido. Sin base de datos vectorial, sin embeddings, sin
  pipeline de indexación.

**CAG no es la opción correcta cuando:**

- **La base de conocimiento es grande y crece continuamente** — miles de documentos que no caben, o
  datos que se actualizan en tiempo real (noticias, inventario, métricas).
- **Necesitas precisión en la selección** — cuando no toda la información es igual de relevante y
  mezclar datos irrelevantes con relevantes confunde al modelo (*context distraction*).
- **El coste por token es una preocupación principal** — cada llamada CAG envía todo el contexto
  completo, lo que significa más tokens de entrada y mayor coste por llamada. Con alto volumen de
  consultas, el coste escala rápido.

## 1.6 Los componentes de una arquitectura CAG

Aunque sea más simple que RAG, CAG tiene componentes bien definidos:

1. **La fuente de conocimiento.** El conjunto de datos que el modelo necesita (en el proyecto, los
   presupuestos históricos). Deben estar **preparados para inyectarse en un prompt**: limpios, bien
   formateados, con lo relevante destacado. Un JSON crudo de 50 campos no es buen contexto; un
   resumen estructurado sí.
2. **La capa de preprocesamiento.** Transforma los datos antes de inyectarlos: selecciona campos
   relevantes, los formatea de forma legible, anonimiza información sensible, agrega datos dispersos.
   Aquí se toman decisiones críticas (qué incluir, qué omitir, en qué formato, con qué detalle) que
   impactan directamente en la calidad y en el consumo de tokens.
3. **El constructor de prompts.** Estructura típica:

   ```
   ┌─────────────────────────────────────┐
   │  SYSTEM PROMPT                       │
   │  (rol del modelo + instrucciones)    │
   ├─────────────────────────────────────┤
   │  CONTEXTO / CONOCIMIENTO             │
   │  (datos de referencia precargados)   │
   ├─────────────────────────────────────┤
   │  MENSAJE DEL USUARIO                 │
   │  (la consulta o transcripción)       │
   └─────────────────────────────────────┘
   ```

   La calidad de cada bloque determina la calidad de la respuesta: un system prompt vago produce
   respuestas vagas; un contexto desordenado, respuestas desordenadas.
4. **El servicio de llamada al LLM.** Gestiona la comunicación con la API del proveedor (OpenAI,
   Anthropic, etc.): claves API seguras, errores y reintentos, límites de tasa, y extracción de la
   información relevante de la respuesta (contenido, tokens consumidos, metadatos).
5. **El postprocesamiento.** La respuesta del modelo es texto. Según el caso: parsearla a JSON,
   validar restricciones, extraer datos estructurados, verificar coherencia. Ejemplo: una estimación
   que diga "10 horas de frontend" pero con un coste de 50.000 € necesita detectarse y corregirse.

## 1.7 CAG en nuestro proyecto: la primera iteración

El estimador de software del Módulo 2 sigue este flujo concreto:

1. **Fuente de conocimiento:** estimaciones históricas (presupuestos previos) almacenadas como
   datos estáticos en el código.
2. **Preprocesamiento:** formatear cada estimación de ejemplo para que sea legible y útil como
   referencia dentro del prompt.
3. **Construcción del prompt:** un system prompt que define al modelo como experto en estimación de
   software, seguido de las estimaciones de ejemplo como contexto, seguido de la transcripción de la
   reunión que se quiere estimar.
4. **Llamada al LLM:** envío del prompt completo a la API y recepción de la estimación.
5. **Postprocesamiento:** extracción de la estimación utilizable (desglose de tareas, horas, costes).

Es la versión más simple posible de un sistema con IA que resuelve un problema real. Sin base de
datos, sin embeddings, sin *retrieval*. Y funciona —porque los datos de referencia son pocos y
caben en el contexto. Cuando crezcan y haya que referenciar cientos de presupuestos, migraremos a
RAG. Pero empezar con CAG permite tener algo funcional rápido y centrarse en lo que importa al
principio: la calidad del prompt, la estructura de los datos de referencia y el diseño de la
respuesta.

## 1.8 La ventana de contexto: el recurso más valioso en CAG

Si CAG consiste en meter todo el conocimiento en la ventana de contexto, **su tamaño es el factor
limitante** de la arquitectura. Dos cosas que todo desarrollador debe saber:

- **El tamaño anunciado no es el tamaño útil.** Un modelo que anuncia 128K tokens no te da 128K para
  tu conocimiento: parte se consume con el system prompt, parte con la respuesta del modelo (tokens
  de salida) y parte con overhead interno. En la práctica, la capacidad útil suele ser el **60-80 %**
  del tamaño anunciado.
- **Más contexto no siempre significa mejor respuesta.** La investigación muestra que los modelos
  **pierden atención a medida que el contexto crece**. La información del principio y del final
  recibe más atención que la del medio: es el efecto **"lost in the middle"**. A partir de cierto
  punto, añadir más contexto degrada la calidad en lugar de mejorarla.

Por eso la gestión eficiente del contexto es una disciplina en sí misma (Parte 4).

## 1.9 De CAG a RAG: el camino natural de evolución

CAG y RAG no son alternativas excluyentes, sino **fases de madurez de un mismo sistema**. Muchos
productos con IA empiezan con CAG porque es la forma más rápida de validar el concepto; una vez
validado, cuando los datos crecen o sube la necesidad de precisión, se evoluciona a RAG añadiendo la
capa de *retrieval*. El recorrido del programa:

```
Módulo 2: CAG
   │ (contexto estático, sin persistencia, todo en el prompt)
   ▼
Módulos 3-4: RAG
   │ (base de datos vectorial, embeddings, búsqueda semántica)
   ▼
Módulo 5: Agentes
     (orquestación, razonamiento multi-paso, tools)
```

Cada fase añade capacidad, pero también complejidad. Entender CAG a fondo es imprescindible para
apreciar qué aporta RAG y cuándo el salto de complejidad está justificado.

---

# PARTE 2 — El paper: *Don't do RAG when CAG is all you need*

Como complemento, el **paper fundacional de CAG**, presentado por **Chan et al.** en la **ACM Web
Conference 2025**. Propone precargar todo el conocimiento relevante en la ventana de contexto del
LLM mediante **KV-cache precomputado**, eliminando la necesidad de *retrieval* en tiempo real y
reduciendo significativamente la latencia y la complejidad del sistema.

Incluye benchmarks en **SQuAD** y **HotPotQA** donde CAG **iguala o supera a RAG en precisión**, con
tiempos de generación notablemente menores. Es la base teórica de la arquitectura que implementa el
proyecto, especialmente en escenarios donde el conocimiento es acotado y puede cargarse íntegramente
en contexto.

- Paper: https://arxiv.org/html/2412.15605v1
- Referencia complementaria (estrategias de contexto): https://blog.logrocket.com/llm-context-problem-strategies-2026

> **Qué es el KV-cache (para cualquiera):** al procesar un texto, el modelo calcula internamente
> unas representaciones intermedias (las "claves y valores" de la atención). Normalmente las recalcula
> en cada llamada. El KV-cache las **guarda precomputadas** para el conocimiento fijo, de modo que el
> modelo no tenga que reprocesar todo el contexto desde cero cada vez. Es lo que hace que precargar
> mucho conocimiento estático salga barato en latencia.

---

# PARTE 3 — Arquitectura escalable en proyectos de IA generativa

## 3.1 ¿Por qué FastAPI para proyectos con IA?

Las aplicaciones que integran LLMs tienen un **perfil de ejecución fundamentalmente distinto** al de
las web tradicionales. Una petición CRUD típica tarda milisegundos; una llamada a un LLM puede
tardar **entre 2 y 30 segundos**.

En un framework síncrono con modelo de threads (Rails con Puma, Django con Gunicorn WSGI), cada
petición al LLM **bloquea un thread completo** durante todo ese tiempo. Bajo carga, los workers se
agotan rápidamente esperando respuestas de la API mientras no hacen nada útil.

FastAPI está construido sobre **ASGI** y soporta `async/await` de forma nativa. Cuando una petición
espera la respuesta del LLM, el *event loop* libera ese hilo para atender otras peticiones. Un solo
proceso FastAPI puede manejar **decenas de peticiones concurrentes** con el mismo consumo de memoria
que un framework síncrono dedicaría a una sola. No es la única opción, pero su modelo de concurrencia
está alineado con la realidad de las cargas con IA: muchas operaciones **I/O-bound de larga
duración**.

## 3.2 El problema del archivo único

FastAPI permite levantar un servidor funcional en cinco líneas. Ventaja para prototipar, problema
cuando el proyecto crece:

```python
# main.py — all in one file
from fastapi import FastAPI
from openai import OpenAI

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

Funciona, pero tiene todo mezclado: configuración del cliente, lógica de negocio (construcción del
prompt, qué contexto inyectar), definición del endpoint HTTP y estructura de la respuesta. Es el
mismo problema de los *fat controllers* de Rails o los views monolíticos de Django. La solución
también es familiar: **separación de responsabilidades**.

## 3.3 Estructura por responsabilidades

```
estimador-cag/
├── app/
│   ├── __init__.py
│   ├── main.py            ← Punto de entrada de la aplicación
│   ├── config.py          ← Configuración centralizada
│   ├── routers/           ← Endpoints HTTP (la capa de transporte)
│   │   └── estimations.py
│   ├── services/          ← Lógica de negocio (la capa inteligente)
│   │   └── llm_service.py
│   ├── schemas/           ← Contratos de datos (request/response)
│   │   └── estimation.py
│   └── context/           ← Datos de referencia para CAG
│       └── examples.py
├── tests/
├── .env
├── .env.example
├── .gitignore
└── pyproject.toml
```

No es una estructura inventada para el curso: es una adaptación de patrones probados en producción,
ajustada a las necesidades de aplicaciones con LLM. Cada directorio tiene una responsabilidad única.

## 3.4 La capa de configuración: `config.py`

Todo proyecto gestiona variables que cambian entre entornos (claves API, URLs, modos). El patrón
estándar en Python con FastAPI es **Pydantic `BaseSettings`**, que combina dos cosas que normalmente
se hacen por separado: cargar variables de entorno **y** validar que tienen el tipo y formato
correctos.

```python
from pydantic_settings import BaseSettings
from functools import lru_cache

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

El decorador `@lru_cache` asegura que la configuración se carga **una sola vez** y se reutiliza: el
equivalente funcional de un singleton sin la maquinaria de patrones de diseño. La ventaja clave de la
validación en carga: si `OPENAI_API_KEY` no está definida, la aplicación **falla al arrancar**, no
cuando un usuario hace la primera petición. **Fallar rápido es una ventaja, no un problema.**

## 3.5 La capa de transporte: `routers/`

Los routers en FastAPI son el equivalente a los *controllers* en MVC. Su responsabilidad es
**exclusivamente la comunicación HTTP**: recibir peticiones, validar el formato de entrada, delegar
en la capa de servicios y formatear la respuesta.

```python
# routers/estimations.py
from fastapi import APIRouter, Depends
from app.schemas.estimation import EstimationRequest, EstimationResponse
from app.services.llm_service import generate_estimation

router = APIRouter(prefix="/api/v1", tags=["estimations"])

@router.post("/estimate", response_model=EstimationResponse)
async def estimate(request: EstimationRequest):
    result = await generate_estimation(request.transcription)
    return result
```

Observa lo que el endpoint **no** hace: no construye prompts, no llama a OpenAI, no gestiona errores
del LLM, no formatea la estimación. Solo recibe, delega y devuelve. **Los endpoints deben ser finos;
la lógica vive en los servicios.**

## 3.6 La capa de negocio: `services/`

Aquí vive la inteligencia de la aplicación: construcción del prompt, inyección de contexto, llamada
al modelo y procesamiento de la respuesta.

```python
# services/llm_service.py
from openai import OpenAI
from app.config import get_settings
from app.context.examples import ESTIMATION_EXAMPLES

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

Esta separación tiene una consecuencia práctica: puedes **testear la lógica de prompts sin hacer
llamadas HTTP**, y **testear los endpoints sin llamar al LLM real** (usando mocks). A medida que el
proyecto crezca, esta capa se subdividirá (`prompt_builder.py`, `llm_client.py`, `postprocessor.py`),
pero en la primera iteración un solo archivo de servicio basta.

## 3.7 Los contratos de datos: `schemas/`

Pydantic no es solo validación: es el **sistema de tipos de tu API**. Cada schema define un contrato
explícito entre tu servicio y sus consumidores.

```python
# schemas/estimation.py
from pydantic import BaseModel, Field

class EstimationRequest(BaseModel):
    transcription: str = Field(
        ...,
        min_length=50,
        description="Transcripción de la reunión con el cliente"
    )

class EstimationResponse(BaseModel):
    estimation: str
    model: str
    provider: str
```

Estos schemas hacen tres cosas automáticamente: **validan** que la transcripción tenga al menos 50
caracteres (evitando llamadas inútiles al LLM), generan **documentación interactiva en Swagger**, y
**serializan** la respuesta al JSON correcto. Es el equivalente a los serializers de Rails o los DTOs
de NestJS con `class-validator`. La ventaja: el contrato está documentado **en código**, no en un
README que nadie actualiza.

## 3.8 Los datos de referencia: `context/`

Esta capa es **específica de la arquitectura CAG**. Contiene los datos que se inyectan como contexto
en cada llamada: en nuestro caso, los ejemplos de estimaciones históricas.

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

En esta primera iteración, los datos son **estáticos** —literalmente definidos en el código—. Es
deliberado: permite iterar sobre la calidad de los ejemplos sin preocuparse por infraestructura.
Cuando evolucionemos a RAG, esta capa será reemplazada por un servicio de búsqueda semántica que
recupera los ejemplos más relevantes de una base de datos vectorial.

Tener esta capa separada desde el principio, aunque sea con datos estáticos, da un **punto de
sustitución limpio**. El servicio LLM no sabe ni le importa si los ejemplos vienen de un diccionario
en memoria o de una query a pgvector. Solo recibe datos formateados.

## 3.9 El punto de entrada: `main.py`

El pegamento que conecta todas las piezas: crea la instancia de FastAPI, registra los routers y
configura el middleware.

```python
# main.py
from fastapi import FastAPI
from app.routers import estimations

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

Mantener `main.py` breve es señal de que la estructura está bien organizada. Si empieza a crecer,
probablemente estés poniendo lógica donde no debería estar.

## 3.10 El flujo completo de una petición

```
Cliente (curl, Swagger, app frontend)
    │
    ▼
main.py ──▶ routers/estimations.py    ← Valida el request con Pydantic
                  │
                  ▼
          services/llm_service.py      ← Construye el prompt con contexto
                  │
                  ▼
          API del LLM (OpenAI/Anthropic)
                  │
                  ▼
          services/llm_service.py      ← Procesa la respuesta
                  │
                  ▼
          routers/estimations.py       ← Serializa el response con el schema
                  │
                  ▼
            Cliente (JSON response)
```

Cada capa hace una cosa y la hace bien. Si falla la llamada al LLM, el error se gestiona en el
servicio, no en el router. Si cambia el formato de respuesta, se modifica el schema, no el servicio.
Si cambia la estrategia de prompt, se modifica el servicio, no el router.

## 3.11 Convenciones que importan

- **Gestión de dependencias con `uv`.** Es el equivalente a Bundler (Ruby) o pnpm/yarn (Node). El
  `pyproject.toml` declara las dependencias y `uv` las resuelve e instala.

  ```bash
  uv sync                              # Instalar dependencias
  uv add httpx                         # Añadir una nueva dependencia
  uv run uvicorn app.main:app --reload # Ejecutar la aplicación
  ```

- **Variables de entorno y seguridad.** Las claves API **nunca** van en el código. Se definen en un
  `.env` que está en el `.gitignore`, y se acceden a través de la capa de configuración. El
  `.env.example` documenta qué variables necesita el proyecto sin exponer valores reales.
- **Versionado de API.** El prefijo `/api/v1` no es decorativo. Cuando tu API tenga consumidores,
  necesitas evolucionar los endpoints sin romper a los clientes existentes: añadir `/api/v2` con un
  nuevo contrato mientras `/api/v1` sigue funcionando.

## 3.12 Cómo evoluciona esta estructura

La estructura es la correcta para la fase CAG y crece de forma natural sin reescribirse:

| Sesión 02 (CAG) | Módulos 3-4 (RAG) añaden | Módulo 5 (Agentes) añaden |
|---|---|---|
| `routers/estimations.py` | `routers/ingestion.py` | más routers |
| `services/llm_service.py` | `services/embedding.py`, `retrieval.py`, `ingestion.py` | más servicios |
| `schemas/estimation.py` | `schemas/document.py` | — |
| `context/examples.py` | `models/` (base, document, chunk), `db/session.py` | — |

Cada módulo **añade archivos nuevos sin modificar la estructura fundamental**. Los routers siguen
siendo delgados, los servicios siguen conteniendo la lógica, los schemas siguen definiendo los
contratos. Lo que cambia es la cantidad de servicios y su complejidad interna, no la arquitectura.

---

# PARTE 4 — Gestión efectiva del contexto en arquitectura CAG

## 4.1 El contexto como recurso finito

En CAG, la ventana de contexto es tu **recurso más valioso y tu limitación más dura**. Todo lo que el
modelo necesita saber debe caber en ella, junto con las instrucciones del system prompt, la consulta
del usuario y el espacio que necesita el modelo para generar su respuesta. No hay una base de datos
vectorial a la que recurrir si algo no cabe: **lo que no está en el contexto, no existe para el
modelo**. Gestionar este recurso con criterio es lo que separa un sistema CAG útil de uno que produce
texto genérico.

## 4.2 Anatomía de la ventana de contexto

```
VENTANA DE CONTEXTO (ej: 128K tokens total)
  ┌──────────────────────────────────────────────────┐
  │ System prompt: instrucciones + rol                │
  │ (~500-1.500 tokens)                               │
  ├──────────────────────────────────────────────────┤
  │ Contexto inyectado: estimaciones de referencia    │
  │ (~2.000-40.000 tokens según cantidad de datos)    │
  ├──────────────────────────────────────────────────┤
  │ Mensaje del usuario: transcripción de reunión     │
  │ (~500-5.000 tokens)                              │
  ├──────────────────────────────────────────────────┤
  │ Respuesta del modelo: estimación generada         │
  │ (~1.000-3.000 tokens)                            │
  ├──────────────────────────────────────────────────┤
  │ Espacio no utilizado (el "desperdicio")           │
  └──────────────────────────────────────────────────┘
```

La suma de todos los bloques **no puede exceder** el tamaño de la ventana. Si lo hace, la llamada
falla o el sistema **trunca contenido silenciosamente** —con resultados impredecibles—. Y un matiz
más sutil: aunque todo quepa, no garantiza que el modelo use bien la información. La atención del
modelo se degrada de forma **no lineal** a medida que el contexto crece: presta más atención al
principio y al final, y tiende a "perderse" con lo del medio (**"lost in the middle"**).

## 4.3 Presupuesto de tokens: planifica antes de construir

Antes de escribir código, haz el ejercicio de presupuesto. Para el estimador con `gpt-4o-mini` (128K)
o `claude-haiku-4-5` (200K), el cálculo orientativo:

| Bloque | Tokens estimados | % del total |
|---|---|---|
| System prompt (instrucciones + formato) | ~1.000 | 1 % |
| Contexto de referencia (estimaciones históricas) | ~5.000-30.000 | 4-23 % |
| Transcripción del usuario | ~1.000-5.000 | 1-4 % |
| Respuesta del modelo | ~1.500-3.000 | 1-2 % |
| Margen de seguridad | ~5.000 | 4 % |
| **Total utilizado** | **~13.500-44.000** | **11-34 %** |

Dos conclusiones. La evidente: en la fase CAG **hay espacio de sobra**; con 5-10 estimaciones de
referencia no nos acercamos al límite, y eso es justo lo que hace viable CAG aquí. La menos obvia
pero más importante: **que tengas espacio no significa que debas llenarlo**. Cada token adicional
tiene un coste **económico** (pagas tokens de entrada) y un coste **atencional** (el modelo procesa
más para encontrar lo relevante). El objetivo no es meter el máximo posible, sino **el mínimo
necesario con la máxima calidad**.

## 4.4 Qué incluir en el contexto (y qué no)

Decidir qué información forma parte del contexto es una **decisión de diseño**, no técnica.

**Información que mejora la respuesta:**

- **Ejemplos de estimaciones previas completas.** No basta con "un e-commerce costó 200 horas": el
  modelo necesita ver el **desglose** (qué tareas, cuántas horas cada una, qué tecnologías, qué
  tamaño de equipo). Es el desglose lo que le permite generar un desglose propio coherente.
- **Patrones de precios y dedicación.** Si en tu empresa un día de backend cuesta 500 € y uno de UX
  cuesta 400 €, el modelo necesita esa referencia para no inventar cifras.
- **Estructura y formato del output esperado.** Incluir un ejemplo de cómo debe verse el resultado
  final es más efectivo que describir el formato en texto.

**Información que degrada la respuesta:**

- **Datos excesivamente detallados que no aportan al patrón.** El historial completo de comunicaciones
  con el cliente de un proyecto de referencia es **ruido** para estimar uno nuevo.
- **Información contradictoria.** Mezclar estimaciones de épocas muy distintas (empresa más pequeña,
  precios distintos, tecnologías obsoletas) hace que el modelo genere estimaciones con patrones
  incompatibles. Mejor pocas referencias relevantes y actuales que muchas heterogéneas.
- **Contexto redundante.** Tres estimaciones de e-commerce muy similares: la segunda y la tercera
  aportan **rendimientos decrecientes**. Mejor una de e-commerce, una de SaaS y una de aplicación
  interna —más diversidad con menos tokens.

## 4.5 Cómo formatear el contexto para el modelo

El formato importa más de lo que parece: un LLM procesa texto, y cómo está estructurado afecta a cómo
lo interpreta. Tres formatos habituales:

- **Texto plano estructurado.** Funciona bien cuando los datos son descriptivos y el modelo necesita
  entender narrativa. Es el **más eficiente en tokens**.

  ```
  --- Estimación de referencia 1 ---
  Proyecto: Plataforma de gestión de inventario
  Tareas:
  Diseño UI/UX: 40 horas a 400 EUR/hora → 16.000 EUR
  Backend API REST: 60 horas a 500 EUR/hora → 30.000 EUR
  Autenticación y roles: 20 horas a 500 EUR/hora → 10.000 EUR
  Total: 120 horas, 56.000 EUR
  Equipo: 2 developers full-stack, 1 diseñador UX (part-time)
  Duración: 6-8 semanas
  ```

- **JSON.** Útil cuando el modelo necesita entender relaciones jerárquicas o cuando el output que
  esperas también es JSON. Los modelos actuales lo procesan con soltura, pero **consume más tokens**
  por los caracteres de estructura (llaves, comillas, indentación).
- **Markdown.** Punto intermedio: estructurado visualmente, jerarquía clara mediante headers, y más
  eficiente que JSON. **Es el formato que usa el proyecto por defecto.**

La recomendación práctica: **usa el formato que más se parezca al output que esperas**. Si quieres que
el modelo genere estimaciones en Markdown con secciones y tablas, dale los ejemplos de referencia en
Markdown con secciones y tablas. El modelo tiende a **replicar los patrones que ve**.

**Separadores y delimitadores.** Cuando incluyes múltiples ejemplos, necesitas delimitar dónde empieza
y termina cada uno. Sin delimitadores claros, el modelo mezcla información:

```
===== ESTIMACIÓN DE REFERENCIA 1 =====
[contenido de la primera estimación]

===== ESTIMACIÓN DE REFERENCIA 2 =====
[contenido de la segunda estimación]

===== FIN DE ESTIMACIONES DE REFERENCIA =====
```

Cumplen dos funciones: ayudan al modelo a entender la estructura, y te ayudan a ti a **debuggear**
cuando la respuesta no es la esperada.

## 4.6 La posición importa: dónde colocar cada cosa

El efecto "lost in the middle" tiene una implicación directa: la información más importante debe estar
**al principio o al final**, nunca enterrada en el medio. En el estimador, eso se traduce en un orden
deliberado:

```
1. System prompt con instrucciones claras        ← PRINCIPIO (máxima atención)
2. Formato esperado del output
3. Estimaciones de referencia (las más relevantes primero)
4. [... más estimaciones ...]
5. Restricciones y reglas específicas             ← CERCA DEL FINAL
6. Transcripción de la reunión (mensaje del usuario) ← FINAL (máxima atención)
```

Las instrucciones van al principio porque definen el comportamiento para toda la interacción. La
transcripción va al final porque es la consulta directa que necesita respuesta inmediata. Las
estimaciones de referencia van en el medio, **ordenadas por relevancia** (la más útil primero). Y las
restricciones, justo antes de la transcripción, donde recibirán atención. No es arbitrario: es una
decisión de ingeniería basada en cómo los modelos distribuyen su atención.

## 4.7 El system prompt: instrucciones que dirigen todo

El system prompt define **quién es el modelo y cómo debe comportarse**, y en CAG también **cómo debe
interpretar el contexto de referencia**. Un system prompt débil:

```
Eres un asistente que ayuda con estimaciones de software.
```

Demasiado vago: el modelo no sabe qué formato usar, qué nivel de detalle dar, ni cómo usar las
estimaciones de referencia. Un system prompt efectivo define **cuatro dimensiones**:

1. **Rol y expertise.** No solo "eres un asistente", sino qué tipo de experto y con qué experiencia.
   Cuanto más específico el rol, más calibrada la respuesta.
2. **Tarea concreta.** Qué debe hacer exactamente: analizar una transcripción de reunión y generar
   una estimación de proyecto de software.
3. **Uso del contexto de referencia.** Cómo interpretar las estimaciones históricas: ¿son ejemplos de
   formato? ¿datos de calibración de precios? ¿proyectos similares? El modelo necesita saber para qué
   están ahí.
4. **Formato del output.** Qué estructura debe tener la respuesta: secciones, campos obligatorios,
   unidades, nivel de detalle. Si no lo especificas, el modelo decide por ti —y no siempre bien.

Un system prompt más efectivo:

```
Eres un consultor senior de software con 15 años de experiencia en estimación de proyectos.
Tu trabajo es analizar transcripciones de reuniones con clientes y generar estimaciones
detalladas de desarrollo de software.

A continuación se incluyen estimaciones de proyectos anteriores de la empresa. Úsalas como
referencia para calibrar tus estimaciones: los precios por hora, la granularidad del desglose
de tareas y la estructura del presupuesto deben ser consistentes con estos ejemplos.

Tu estimación debe incluir:
1. Resumen del proyecto (2-3 frases)
2. Desglose de tareas con horas estimadas y coste
3. Equipo recomendado
4. Duración total estimada
5. Riesgos o supuestos clave

Usa EUR como moneda. Redondea las horas a múltiplos de 5.
```

La diferencia parece obvia al compararlos, pero en la práctica muchos sistemas en producción funcionan
con prompts del primer tipo. **La calidad del system prompt es posiblemente el factor que más impacta
en la calidad del output, y sin embargo es el componente al que menos tiempo se le suele dedicar.**

## 4.8 Preprocesamiento: la capa invisible que marca la diferencia

Entre los datos en crudo y el contexto que llega al modelo hay una capa de transformación (en la
estructura FastAPI, vive en el servicio: la función que toma los datos de `context/examples.py` y los
convierte en texto listo para el prompt). Operaciones típicas:

- **Selección de campos relevantes.** Un presupuesto completo puede tener 50 campos. El modelo no
  necesita el ID interno, la fecha de creación, el email del comercial ni las condiciones de pago para
  estimar horas y coste. Incluirlos consume tokens sin aportar valor.
- **Normalización de formatos.** Si un presupuesto usa "días" y otro "horas", el contexto debe
  normalizarlos a una unidad común. El modelo puede manejar inconsistencias, pero cada una introduce
  una pequeña probabilidad de error.
- **Cálculo de campos derivados.** Si el presupuesto tiene `quantity: 15` y `unit_price: 500` pero no
  tiene `total`, calcularlo y añadirlo evita que el modelo tenga que hacer aritmética —algo en lo que
  los LLMs no son especialmente fiables.
- **Anonimización.** Nombres de clientes, emails u otra información sensible deben eliminarse o
  generalizarse antes de incluirlos. El modelo no necesita saber que era para "Empresa X" —necesita
  saber que era una plataforma de e-commerce con 50K usuarios mensuales.

Estas transformaciones parecen menores, pero su efecto acumulativo es sustancial. Un contexto limpio,
consistente y sin ruido produce respuestas significativamente mejores que un volcado directo de datos
en crudo.

## 4.9 Cuántos ejemplos de referencia incluir

La respuesta no es "todos los que quepan", sino "los que aporten sin generar ruido":

- **2-3 ejemplos** son suficientes para que el modelo entienda el formato, la escala de precios y el
  nivel de desglose. Es el **mínimo viable** para un CAG que produzca resultados utilizables.
- **5-7 ejemplos** son el **punto dulce** para la mayoría de los casos: suficiente diversidad de tipos
  de proyecto (web, móvil, API, integración) para que el modelo calibre bien sin inundar el contexto.
- **Más de 10 ejemplos** empiezan a tener rendimientos decrecientes. El octavo presupuesto de
  e-commerce no aporta nada que los tres primeros no hayan cubierto, pero consume tokens y diluye la
  atención.

La evolución natural del sistema —cuando 10 ejemplos no bastan y necesitas cientos— es exactamente el
momento en que CAG deja de ser la arquitectura adecuada y la **migración a RAG** está justificada. En
RAG, un servicio de búsqueda semántica selecciona los 5-7 más relevantes de entre cientos, combinando
lo mejor de ambos mundos: la precisión de la selección con la eficiencia de un contexto acotado.

## 4.10 Iteración sobre el contexto: un proceso continuo

Una ventaja poco mencionada de CAG es la **velocidad de iteración**. Como los datos viven en el código
(`context/examples.py`), cambiar un ejemplo, reformatear o ajustar el system prompt es **inmediato**.
No hay que re-indexar una base de datos, recalcular embeddings ni esperar a un pipeline de ingesta.

```
1. Ejecutar una estimación con la transcripción de prueba
2. Evaluar la calidad del resultado
3. Identificar el problema:
   ¿Formato inadecuado?       → Ajustar el system prompt
   ¿Precios descalibrados?    → Mejorar los ejemplos de referencia
   ¿Desglose demasiado genérico? → Añadir más detalle a los ejemplos
   ¿Información irrelevante en el output? → Añadir restricciones
4. Modificar el contexto
5. Volver al paso 1
```

Cada iteración es cuestión de segundos: modificas un string, reinicias el servidor (o `--reload` lo
hace por ti), y lanzas otra petición. Esta velocidad se pierde parcialmente al migrar a RAG (los
cambios requieren re-vectorización). Es una razón para **explotar la fase CAG al máximo**: invertir
tiempo ahora en el formato de contexto óptimo y el system prompt más efectivo ahorra esfuerzo después.

## 4.11 Errores comunes en la gestión de contexto

- **Contexto demasiado genérico.** Ejemplos muy distintos entre sí y del proyecto a estimar: el modelo
  no tiene un patrón claro y la respuesta es una media difusa que no refleja ningún caso real.
- **Instrucciones contradictorias.** Si el system prompt dice "sé conciso" pero los ejemplos son
  extensos, el modelo recibe señales opuestas. **Los ejemplos suelen ganar** (el modelo imita lo que
  ve), así que asegúrate de que instrucciones y ejemplos estén alineados.
- **Ausencia de formato de output.** Sin especificación clara, cada llamada produce una estructura
  diferente (una tabla, una lista, un párrafo). Para producción, la consistencia del formato es tan
  importante como la calidad del contenido.
- **Volcado de datos sin curación.** Pegar un JSON de 200 líneas directamente es la forma más segura de
  obtener resultados pobres. La curación del contexto es responsabilidad del desarrollador, no del
  modelo.
- **Ignorar el coste acumulativo.** Cada llamada envía todos los tokens de referencia. Con 10.000
  tokens de contexto y 1.000 llamadas al día, son **10 millones de tokens de entrada al día solo en
  contexto**. El coste se multiplica por el volumen de uso.

---

# PARTE 5 — Arquitectura de conversaciones con modelos

## 5.1 La interfaz real con un LLM: un array de mensajes

Cuando usas ChatGPT o Claude desde el navegador, parece una conversación fluida donde el modelo
"recuerda" lo que dijiste hace tres turnos. Pero es una **ilusión de la interfaz**. Por debajo, cada
vez que envías un mensaje, la aplicación empaqueta **toda la conversación completa** —desde el primer
mensaje hasta el último— en un único array de objetos JSON y lo envía al modelo.

El modelo **no tiene memoria entre llamadas**. No "recuerda" nada: lee toda la conversación de
principio a fin, genera una respuesta, y se olvida de todo. En la siguiente llamada vuelve a recibir
todo el historial y lo procesa como si fuera la primera vez. Es posiblemente la diferencia más
importante entre la percepción del usuario y la realidad técnica, y como desarrolladores trabajamos
con la realidad.

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

Todo lo que el modelo sabe sobre la interacción está en este array. **Si no está aquí, no existe.**

## 5.2 Los tres roles: system, user, assistant

Cada mensaje tiene un **rol** que le indica al modelo quién lo dice y cómo interpretarlo.

- **`system` — las reglas del juego.** Define el comportamiento global del modelo para toda la
  conversación. Es la única parte que el modelo interpreta como **instrucciones de configuración**, no
  como contenido conversacional. Se envía en **cada llamada**: una conversación de 20 turnos envía el
  system prompt 20 veces, consumiendo tokens cada vez. Una razón más para que sea conciso —cada palabra
  innecesaria se paga multiplicada por el número de interacciones.
- **`user` — lo que pide el ser humano.** Las entradas del usuario. En el estimador, el primer mensaje
  de usuario contiene la transcripción de la reunión. Cada turno del usuario añade un nuevo mensaje con
  este rol.
- **`assistant` — lo que dijo el modelo.** Las respuestas previas del modelo. Aquí viene lo
  contraintuitivo: en una conversación multi-turno, **tú eres responsable de guardar las respuestas del
  modelo e incluirlas en las llamadas siguientes**. El modelo no lo hace por ti. Si el usuario pide
  "ajusta las horas de diseño a 50", el modelo necesita ver su propia respuesta anterior en el array
  para saber qué estimación está ajustando.

## 5.3 Single-turn vs multi-turn: dos modelos de interacción

- **Modo single-turn (una pregunta, una respuesta).** Cada llamada es independiente: el usuario envía
  una transcripción, el modelo devuelve una estimación, y la interacción termina. No hay historial que
  gestionar. Es el modo del ejercicio pre-sesión, perfectamente válido para muchos casos. **Ventaja:**
  simplicidad, no hay estado entre peticiones. **Desventaja:** no puedes iterar sobre una estimación
  ("sube las horas de backend") sin repetir todo el contexto desde cero.

  ```python
  # Single-turn: no hay historial
  messages = [
      {"role": "system", "content": system_prompt_con_contexto},
      {"role": "user", "content": transcripcion_de_reunion}
  ]
  ```

- **Modo multi-turn (conversación iterativa).** El usuario y el modelo mantienen una conversación donde
  cada turno construye sobre los anteriores: el usuario pide una estimación, la revisa, pide ajustes, el
  modelo los aplica. **Ventaja:** una experiencia mucho más rica, el usuario refina en un diálogo
  natural. **Desventaja:** la conversación **consume tokens de forma acumulativa** —cada turno nuevo
  incluye todos los anteriores, y el coste crece con cada interacción.

## 5.4 Gestión del historial en memoria

En modo multi-turn necesitas un mecanismo para almacenar el historial. En la fase CAG, la
implementación más directa es **mantenerlo en memoria** —una lista de Python que crece con cada turno.

```python
class ConversationManager:
    def __init__(self, system_prompt: str):
        self.messages = [
            {"role": "system", "content": system_prompt}
        ]

    def add_user_message(self, content: str):
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str):
        self.messages.append({"role": "assistant", "content": content})

    def get_messages(self) -> list:
        return self.messages.copy()
```

Es intencionadamente simple: sin persistencia en disco, sin base de datos. Si el servidor se reinicia,
las conversaciones se pierden. Es aceptable en esta fase —la persistencia y la memoria a largo plazo son
temas de sesiones posteriores—. Lo que **sí** necesitas gestionar desde el principio es qué pasa cuando
la conversación crece demasiado.

## 5.5 El problema del crecimiento: cuándo el historial no cabe

Cada turno añade tokens. Un turno típico consume 1.000-4.000 tokens, y con un system prompt que ya
incluye las estimaciones de referencia (5.000-30.000 tokens), la ventana se llena progresivamente:

```
System prompt con contexto CAG:      15.000 tokens
Turno 1 (user + assistant):           3.000 tokens
Turno 2 (user + assistant):           2.500 tokens
Turno 3 (user + assistant):           2.000 tokens
Turno 4 (user + assistant):           3.500 tokens
Turno 5 (user + assistant):           2.000 tokens
Espacio para respuesta del turno 6:   3.000 tokens
─────────────────────────────────────────────────
Total:                               31.000 tokens
```

31.000 está lejos del límite de 128K, pero el crecimiento es real y en conversaciones largas se
convierte en problema —no solo de espacio, sino de **calidad** (más tokens = más coste y menos atención
efectiva). Tres estrategias para gestionarlo:

- **Estrategia 1: Ventana deslizante.** La más simple: mantienes solo los últimos N turnos y descartas
  los más antiguos (el system prompt siempre se conserva). Predecible y fácil, pero si el usuario dijo
  algo importante en el turno 1 y estás en el turno 15, esa información desaparece: el modelo "olvida"
  decisiones tempranas.

  ```python
  def get_messages_windowed(self, max_turns: int = 10) -> list:
      system = [self.messages[0]]      # Siempre conservar el system prompt
      history = self.messages[1:]      # Todo lo demás
      if len(history) > max_turns * 2:
          history = history[-(max_turns * 2):]
      return system + history
  ```

- **Estrategia 2: Resumen acumulativo (compactación).** En lugar de descartar turnos antiguos, los
  **resumes** en un mensaje compacto al principio de la conversación. Cuando el historial alcanza cierto
  tamaño, generas un resumen usando el propio LLM y reemplazas los turnos antiguos por ese resumen.
  **Ventaja:** conserva la información esencial de toda la conversación. **Desventaja:** el resumen es una
  operación adicional que consume tokens y tiempo, y su calidad depende de la instrucción de resumir.

  ```
  [system prompt]
  [resumen de turnos 1-8: "El usuario solicitó una estimación para una plataforma de
   reservas. Se acordó un equipo de 3 personas, duración de 8 semanas. Se ajustaron las
   horas de diseño de 40 a 60."]
  [turno 9: user] [turno 9: assistant] [turno 10: user]
  → modelo responde
  ```

- **Estrategia 3: Híbrida con priorización.** Combina la ventana deslizante con el **marcado de turnos
  importantes**. Ciertos turnos se marcan como "ancla" (donde se definió el alcance del proyecto o se
  tomó una decisión clave) y nunca se descartan; los intermedios sí. Es la más sofisticada y la que
  mejor funciona en producción, pero requiere criterio para decidir qué es "ancla". Para la fase actual,
  la ventana deslizante es suficiente.

  ```
  [system prompt]
  [turno 1: definición del proyecto — ANCLA, nunca se descarta]
  [turno 5: decisión sobre equipo — ANCLA, nunca se descarta]
  [turnos 8-10: últimos turnos completos — ventana deslizante]
  → modelo responde
  ```

## 5.6 El patrón request-response en la práctica

Todo junto en el servicio del estimador:

```python
# services/llm_service.py
async def generate_estimation(
    transcription: str,
    conversation_history: list | None = None
) -> dict:
    system_prompt = build_system_prompt()  # Incluye contexto CAG

    if conversation_history:
        # Multi-turn: usar el historial existente
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": transcription})
    else:
        # Single-turn: solo system + user
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": transcription}
        ]

    response = client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=messages
    )
    assistant_message = response.choices[0].message.content
    return {
        "estimation": assistant_message,
        "model": settings.LLM_MODEL,
        "usage": {
            "input_tokens": response.usage.prompt_tokens,
            "output_tokens": response.usage.completion_tokens
        }
    }
```

La función acepta un historial **opcional**: si viene vacío o nulo, funciona en single-turn; si viene
con turnos previos, en multi-turn. El router decide el modo según la petición del cliente; el servicio
no necesita saber por qué. Esta separación es coherente con la estructura FastAPI: el servicio **no
gestiona estado HTTP**. El estado conversacional (el historial) vive fuera —en el router, el cliente o
un middleware de sesión—. El servicio solo recibe mensajes y devuelve respuestas.

## 5.7 Diferencias entre proveedores que afectan a tu código

La estructura `messages` con roles `system`/`user`/`assistant` es un **estándar de facto**, pero los
proveedores tienen diferencias que tu código debe contemplar si soportas más de uno:

- **System prompt.** OpenAI lo acepta como un mensaje más dentro del array. Anthropic lo recibe como
  **parámetro separado** (`system="..."`), fuera del array de mensajes. Si abstraes proveedores,
  necesitas separar el system prompt del resto antes de la llamada.
- **Alternancia estricta de roles.** Algunos modelos requieren que los mensajes alternen estrictamente
  entre `user` y `assistant`. Dos mensajes `user` consecutivos producen un error. Si necesitas enviar
  información adicional entre turnos (por ejemplo, resultados de una herramienta), consolídala en un solo
  mensaje `user` o usa el rol `tool` que algunos proveedores soportan.
- **Tokens de respuesta.** El parámetro `max_tokens` limita cuántos tokens genera el modelo. Si la
  estimación requiere un desglose extenso y el límite es bajo, la respuesta se corta abruptamente. Para
  estimaciones de software, 2.000-4.000 suele bastar. **Configúralo explícitamente** en lugar de depender
  del valor por defecto del proveedor, que varía.
- **Nombre del campo de respuesta.** OpenAI devuelve la respuesta en `response.choices[0].message.content`.
  Anthropic, en `response.content[0].text`. Si abstraes proveedores, tu servicio necesita normalizar estas
  diferencias.

Parecen menores con un solo proveedor, pero son una fuente constante de bugs si soportas varios sin una
capa de abstracción adecuada. La **Sesión 03** verá patrones de diseño para wrappers de modelos que
resuelven exactamente esto.

## 5.8 De la conversación al producto: consideraciones de diseño

Más allá de la implementación, hay decisiones de **diseño de producto** que afectan a cómo estructuras la
conversación:

- **¿Tu sistema es conversacional o transaccional?** El estimador en su forma básica es **transaccional**:
  el usuario envía una transcripción, obtiene una estimación. Si añadimos la capacidad de refinar en un
  diálogo, se vuelve **conversacional**. Ambos son válidos, pero la implementación difiere: el transaccional
  no necesita gestionar historial; el conversacional sí.
- **¿Quién controla el contexto de referencia?** En CAG, el contexto de estimaciones históricas se inyecta
  automáticamente en cada llamada; el usuario no lo ve ni lo controla. Pero podrías diseñar una variante
  donde el usuario **selecciona** qué presupuestos usar como referencia. Eso cambia la estructura del
  prompt: los datos de referencia dejan de ser parte del system prompt y pasan a ser parte del mensaje del
  usuario.
- **¿Cómo indicas al usuario los límites del modelo?** Si la conversación es muy larga y empiezas a truncar
  historial, el modelo puede "olvidar" decisiones anteriores. Gestionar esa expectativa —informar al usuario
  cuando se acerca al límite, ofrecer "reiniciar" con un resumen— es una decisión de producto, no solo de
  ingeniería.

---

## Chuleta de una página

**CAG (Cache Augmented Generation)**
- Precargar **todo** el conocimiento relevante en la ventana de contexto. Sin búsqueda, sin base de datos
  vectorial, sin *retrieval*.
- Elimina 3 problemas de RAG: latencia de búsqueda, errores de selección, complejidad de infraestructura.
- A cambio: los datos deben **caber** en la ventana, y cada llamada paga **todos** los tokens de contexto.
- **Usa CAG cuando:** datos acotados, estáticos, necesitas simplicidad y velocidad.
- **No uses CAG cuando:** datos masivos/dinámicos, o el coste por token a alto volumen es crítico.
- Es la **primera fase**: CAG (Mód. 2) → RAG (Mód. 3-4) → Agentes (Mód. 5).

**Ventana de contexto**
- Tamaño anunciado ≠ útil (cuenta con un **60-80 %** efectivo).
- "Lost in the middle": atención máxima al **principio y al final**, mínima en el medio.
- Presupuesta tokens **antes** de codificar. Menos es más: mínimo necesario, máxima calidad.

**Estructura del proyecto (FastAPI por capas)**
- `routers/` (transporte, **delgado**) → `services/` (lógica, LLM) → `schemas/` (contratos Pydantic) →
  `context/` (datos CAG, punto de sustitución CAG↔RAG).
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
- Roles: `system` (config global) / `user` (humano) / `assistant` (respuestas previas del modelo — **tú** las guardas).
- **Single-turn** (transaccional, sin historial) vs **multi-turn** (conversacional, coste acumulativo).
- Gestión del historial: **ventana deslizante** (simple) / **resumen acumulativo** / **híbrida con anclas**.
- Proveedores difieren: system como mensaje (OpenAI) vs parámetro (Anthropic), alternancia de roles,
  `max_tokens`, campo de respuesta (`choices[0].message.content` vs `content[0].text`).

**Paper de referencia:** Chan et al., *Don't do RAG when CAG is all you need*, ACM Web Conference 2025 —
https://arxiv.org/html/2412.15605v1
