# Sesión 03 — De un endpoint que funciona a un sistema de producción (versión clara)

> Versión simplificada del resumen de teoría de la Sesión 3 (autor: Antonio Pérez).
> Misma información, menos paja. Cada término técnico se explica en una frase.
> **Hilo conductor:** en la Sesión 2 montamos un endpoint FastAPI que estima software con CAG; aquí construimos todo lo que lo rodea para convertirlo en un producto serio — concentrado en un único **wrapper** entre el endpoint y los proveedores de LLM.

---

## Glosario base (léelo una vez y vuelve cuando haga falta)

| Término | Qué es, en una frase |
|---|---|
| **CAG** (*Context-Augmented Generation*) | Inyectar contexto/ejemplos en el *prompt* para guiar al modelo. |
| **LLM** | *Large Language Model*; el modelo de lenguaje (GPT, Claude...) al que pedimos la estimación. |
| **Wrapper / capa de abstracción** | Código intermedio que unifica el acceso a varios proveedores de LLM. |
| **Proveedor** | Quien sirve el modelo: OpenAI, Anthropic, etc. |
| **Fallback** | Rotar automáticamente a otro proveedor cuando el primero falla. |
| **SDK** | La librería oficial de cada proveedor para llamar a su API desde código. |
| **Endpoint** | Una URL del backend (p. ej. `/estimate`) que recibe una petición y devuelve respuesta. |
| **Latencia** | Cuánto tarda en responder. |
| **Token** | Unidad en que el LLM cuenta texto (≈ trozo de palabra); se factura por tokens. |
| **Streaming** | Enviar la respuesta por fragmentos según se genera, no de golpe al final. |
| **Caché** | Guardar una respuesta ya calculada para no volver a pagarla ni recalcularla. |

---

## El hilo conductor

En la Sesión 2 construimos algo que **funciona**: un endpoint FastAPI que recibe la transcripción de una reunión y devuelve una estimación usando CAG. Pero "funciona en mi máquina" y "funciona en producción" son cosas distintas. Esta sesión es la "carrocería" que envuelve ese motor. Son cinco piezas:

| Pieza | Problema que resuelve | Pregunta humana |
|---|---|---|
| **Interfaz** | Que la use alguien que no programa | "¿Cómo lo prueba un *project manager*?" |
| **Abstracción + fallback** | No depender de un solo proveedor | "¿Y si OpenAI se cae o sube precios?" |
| **Cacheo** | No pagar dos veces por lo mismo | "¿Por qué pagar de nuevo si la pregunta es idéntica?" |
| **Streaming** | Ver la respuesta mientras se genera | "¿Por qué miro un *spinner* 8 segundos?" |
| **Observabilidad** | Saber qué pasó cuando algo falla | "¿Qué prompt se envió y cuánto costó?" |

> Casi todo se construye sobre un **wrapper** que se coloca entre el endpoint y los proveedores, y concentra abstracción, *fallback*, caché, *streaming* y *logging*. Se monta a lo largo de la sesión en vivo.

---

## 1. Interfaces conversacionales: Streamlit, Gradio y Chainlit

### El problema

Tienes un endpoint que recibe texto y devuelve respuesta del LLM, pero la única forma de probarlo es con `curl`, Postman o Swagger (herramientas de programador). Para que lo use una persona no técnica necesitas una **interfaz web**. Construirla desde cero arrastra mucha "fontanería" (estado de la conversación, *streaming*, indicadores de carga). Los *frameworks* de UI para IA permiten una interfaz funcional **en Python puro**, sin JavaScript, a menudo en menos de 50 líneas. Hay tres dominantes, cada una nacida con un propósito distinto.

### Streamlit — el generalista

> **Streamlit** = framework para *dashboards* y apps de datos que con el tiempo añadió chat (`st.chat_message`, `st.chat_input`). Su ADN es de propósito general.

Lo **más importante** de entender es su modelo de ejecución: *cada interacción re-ejecuta todo el script de arriba a abajo*. Simplifica el desarrollo (se lee como un guion secuencial), pero obliga a usar `st.session_state` para **persistir cualquier dato** entre interacciones — incluido el historial. Un chat con *streaming* son ~25 líneas; `st.write_stream` recibe el *stream* del SDK y lo renderiza progresivamente.

- **Fortalezas:** la mayor comunidad, el ecosistema de componentes más rico (gráficos, tablas, mapas, *file uploads*, *sidebars*), *multipage* nativo y *deployment* gratuito en Streamlit Community Cloud. Si la app necesita **algo más que chat**, es lo más natural.
- **Limitaciones:** la re-ejecución completa complica el estado complejo; sin procesos en *background*, *websockets* persistentes ni tiempo real sin *workarounds*. Personalizar CSS es luchar contra el framework. Para chat en producción con auth, persistencia e hilos, se queda corto.

### Gradio — la demo rápida

> **Gradio** = framework del ecosistema Hugging Face para **envolver cualquier función Python en una interfaz web** (filosofía `input → función → output`). Para chat ofrece `gr.ChatInterface`.

- **Fortalezas:** la ruta más rápida de "tengo una función Python" a "tengo una demo compartible". `demo.launch(share=True)` genera una **URL pública temporal (72 h)** sin *deployment* — ideal para enseñar un prototipo en 5 minutos. Integración con Hugging Face Spaces para demos permanentes. Componentes **multimodales** nativos (imagen, audio, vídeo) que los demás no tienen.
- **Limitaciones:** estado más limitado (`gr.State` funciona pero es menos intuitivo que `session_state`); *layouts* multipágina no nativos. Para chat en producción con auth, persistencia e hilos, se queda sin capacidades.

### Chainlit — el especialista en chat

> **Chainlit** = framework diseñado **exclusivamente** como capa de UI para apps conversacionales con LLMs (chatbots, agentes, asistentes). Construido sobre `asyncio` desde su base.

Trae de serie lo que en Streamlit/Gradio hay que hacer a mano: *streaming* nativo, *threading* de mensajes, visualización paso a paso del razonamiento del agente, *feedback*, autenticación y persistencia.

- **Fortalezas:** la **observabilidad integrada** es su rasgo diferencial — ves la "cadena de pensamiento" del agente (qué *prompt* se envió, qué herramientas usó, qué devolvió cada paso), indispensable para depurar agentes complejos. Integración nativa con LangChain y LlamaIndex. Auth con Azure AD, Google y otros. Persistencia *out-of-the-box*.
- **Limitaciones:** su foco en chat lo hace incómodo para UI no conversacional. Librería de componentes mucho más pequeña (sin gráficos, *dataframes* ni mapas). Comunidad más reducida y docs aún con asperezas.

### ¿Y construirlo desde cero?

Conectar HTML/CSS/JS directamente al backend FastAPI tiene sentido cuando necesitas **control total** de la UX, cuando el chat es solo un componente de una app mayor, o cuando el diseño es incompatible con los frameworks. Ventaja: control absoluto. Desventaja: implementas tú estado, renderizado, *streaming* (SSE o WebSockets) y carga. Para producción con UX específica suele ser la mejor opción a largo plazo; para prototipar, los frameworks ahorran tiempo.

### Tabla comparativa

| Criterio | Streamlit | Gradio | Chainlit |
|---|---|---|---|
| Diseñado para | Apps de datos generalistas | Demos de modelos ML | Chatbots y agentes IA |
| Chat nativo | Sí (desde v1.28) | Sí (`ChatInterface`) | Sí (core del framework) |
| Streaming | `st.write_stream` | Soporte nativo | Nativo y optimizado |
| Estado | `session_state` (potente) | `gr.State` (limitado) | Gestión de sesión nativa |
| Componentes extra | Gráficos, tablas, mapas | Multimodales | Mínimos (foco en chat) |
| Observabilidad de agentes | No nativa | No nativa | Integrada (*chain of thought*) |
| Autenticación | Básica | Básica | Azure AD, Google, custom |
| Persistencia de chat | Manual (`session_state`) | Manual | Nativa |
| Deployment | Streamlit Cloud (gratis) | HF Spaces / *share link* | Docker / self-hosted |
| Comunidad | La mayor | Grande (Hugging Face) | En crecimiento |
| Curva de aprendizaje | Baja | Muy baja | Media |

> **Regla práctica:** *Streamlit* si necesitas más que chat o prototipar rápido (es el del ejercicio pre-sesión); *Gradio* para demos rápidas y multimodales; *Chainlit* para una app de chat seria con agentes y observabilidad.

---

## 2. Abstracción de proveedores y estrategias de *fallback*

### El problema

El estimador de la Sesión 2 está **acoplado a un único proveedor**: importa `openai`, llama a `client.chat.completions.create()` y parsea la respuesta con la estructura específica de OpenAI. Probar Claude no es cambiar una variable: hay que reescribir la llamada, adaptar el parseo, manejar errores distintos y ajustar el conteo de tokens. Y esto importa: **los proveedores se caen** (OpenAI y Anthropic han tenido incidentes), **los precios cambian**, **aparecen modelos mejores cada trimestre** y **las APIs evolucionan**.

> La industria ya lo resolvió: lo que un **ORM** (SQLAlchemy, Prisma) hace para bases de datos — abstraer para cambiar de MySQL a PostgreSQL sin reescribir la app —, una **capa de abstracción de LLMs** lo hace para modelos de lenguaje.

### Qué es una capa de abstracción de LLMs

> **Capa de abstracción de LLMs** = una interfaz unificada entre tu código y los proveedores: llamas a una función genérica (p. ej. `completion()`) y la capa la traduce al formato del proveedor configurado.

```python
# Acoplado a OpenAI
from openai import OpenAI
client = OpenAI()
response = client.chat.completions.create(model="gpt-4o-mini", messages=[...])

# Desacoplado: el proveedor es configuración, no código
from litellm import completion
response = completion(model="gpt-4o-mini", messages=[...])  # cambiar a "claude-haiku-4-5" = 0 cambios
```

> El cambio parece menor pero la implicación es enorme: **cambiar de proveedor pasa a ser un cambio de configuración**, no de código. La lógica de negocio (*system prompt*, parseo, validación) no se toca.

### ¿Construir tu propio *wrapper* o usar uno existente?

Escribir el tuyo parece limpio al principio, pero esa clase **crece rápido**. Problemas de un *wrapper* ad-hoc en producción:

- **Mantenimiento continuo:** cada cambio de API de un proveedor obliga a actualizarlo. Con dos es manejable; con cinco, es un trabajo a tiempo parcial.
- **Re-implementar lo ya resuelto:** reintentos con *backoff* exponencial, conteo de tokens por modelo, *rate limits*, normalización de respuestas, manejo de errores por SDK.
- **Casos borde no anticipados:** *timeouts* parciales, respuestas truncadas, errores de red intermitentes, cambios silenciosos en APIs — aparecen en producción. Un open source con miles de usuarios ya los vio; tu *wrapper* casero no.
- **El coste real:** el tiempo en el *wrapper* es tiempo que no inviertes en el producto.

Un *wrapper* propio solo tiene sentido cuando tu necesidad es muy específica y nada la cubre bien.

### Herramientas disponibles

**LiteLLM — el agregador ligero** *(la que usaremos)*
> **LiteLLM** = librería Python open source con interfaz compatible para **+100 modelos de +10 proveedores**. Ligera: solo estandariza la llamada, no impone *chains* ni *agents*.

Más allá de la abstracción ofrece:
- *Router* con *fallback* y reintentos (lista de modelos por prioridad; si el primero falla, intenta el siguiente; *backoff* configurable).
- *Tracking* de costes (tokens y coste por llamada, modelo, usuario).
- *Rate limiting* y modo *proxy* (servidor intermedio para varios servicios).

```python
from litellm import Router
router = Router(
    model_list=[
        {"model_name": "estimador", "litellm_params": {"model": "gpt-4o-mini", "api_key": "sk-..."}},
        {"model_name": "estimador", "litellm_params": {"model": "claude-haiku-4-5", "api_key": "sk-ant-..."}},
    ],
    fallbacks=[{"estimador": ["estimador"]}],
    num_retries=2,
)
# El código de negocio solo conoce "estimador" — no sabe si responde OpenAI o Anthropic
response = router.completion(model="estimador", messages=[...])
```

> ⚠️ **Nota de seguridad de dependencias:** en marzo de 2026, las versiones **1.82.7 y 1.82.8 de LiteLLM en PyPI fueron comprometidas con código malicioso**. Se detectó rápido, pero es un recordatorio real del riesgo. Buena práctica: **fijar versiones** en `pyproject.toml` y verificar *hashes*. Aplica a cualquier dependencia, no solo a LiteLLM.

**OpenRouter — el marketplace**
> **OpenRouter** = un mercado de modelos: una sola *API key* da acceso a decenas de modelos vía API unificada, con *routing*, facturación consolidada y balanceo.

Ventaja: simplicidad operativa (una cuenta, una factura). Desventaja: **tus datos pasan por sus servidores** (problema de *compliance*) y aplican un margen. Útil para prototipos; para producción con datos sensibles, la mayoría prefiere llamar directo con una capa local como LiteLLM.

**LangChain — el framework completo**
> **LangChain** = framework de orquestación de LLMs mucho mayor (*chains*, *agents*, memoria, *tools*); incluye abstracción de proveedores como una parte.

Para el propósito concreto de abstraer + *fallback* está **sobredimensionado** ("usar Rails para servir una página estática"). Brilla en orquestación compleja (módulos 4 y 5). Para esta sesión, LiteLLM es lo correcto por su menor complejidad.

### Estrategias de *fallback*

- **Fallback secuencial (el más común):** lista ordenada de proveedores; si el primero falla (*timeout*, error 500, *rate limit*) pasa al segundo. El orden refleja tu preferencia (primero el más barato/rápido). Es lo que configura el *Router* de LiteLLM.
- **Fallback por tipo de error:** no todos los errores merecen *fallback*. Una *API key* inválida no se arregla reintentando; un *timeout* sí; un 429 (*rate limit*) justifica esperar/rotar.

  ```python
  for provider in providers:
      try:
          return provider.call(messages)
      except AuthenticationError:
          raise                 # No tiene sentido reintentar ni rotar
      except RateLimitError:
          continue              # Rotar al siguiente proveedor
      except TimeoutError:
          if provider.retries_left > 0: provider.retry_with_backoff()
          else: continue        # Agotar reintentos y rotar
      except ServerError:
          continue              # El proveedor tiene problemas, rotar
  raise AllProvidersFailedError()
  ```
- **Routing por complejidad (avanzado):** enrutar según dificultad. Transcripciones cortas → modelo económico (`gpt-4o-mini`, `claude-haiku-4-5`); complejas → modelo potente (`gpt-4o`, `claude-sonnet-4-6`). No es *fallback* sino *routing* inteligente, pero comparte la filosofía de **desacoplar la elección del modelo de la lógica de negocio**. Se ve en las sesiones de orquestación.

### Criterios para elegir herramienta

- **Privacidad de datos:** si no pueden pasar por terceros (*compliance*, GDPR, datos sensibles), descarta OpenRouter y *proxies* externos. LiteLLM y *wrappers* propios mantienen llamadas directas.
- **Complejidad de la app:** solo abstracción + *fallback* → LiteLLM; orquestación de agentes → LangChain; *marketplace* con factura consolidada → OpenRouter.
- **Overhead operativo:** LiteLLM como librería = `pip install` + una línea; como *proxy* requiere infra; LangChain implica aprender un framework.
- **Madurez:** LiteLLM tiene +40 000 estrellas en GitHub y es dependencia transitiva de muchos frameworks de agentes; a estas alturas todas son maduras.

> **Idea clave:** la abstracción de proveedores **no es un lujo — es un requisito** para cualquier sistema con LLMs en producción. El coste de implementarla es mínimo; el de no tenerla aparece el día que tu proveedor se cae, sube precios o deprecia tu modelo.

---

## 3. Cacheo inteligente de respuestas de LLMs

### El problema

Un *project manager* pega la **misma transcripción dos veces**. Sin caché, el sistema hace dos llamadas, paga los tokens dos veces y el usuario espera dos veces 3-5 segundos — para una respuesta casi idéntica. No es excepcional: las apps reales con LLMs muestran **repetición constante**. Según datos de producción de 2026, el cacheo semántico alcanza **40-70 %** de aciertos con tráfico real. Tres beneficios:

- **Latencia:** respuesta cacheada en microsegundos (*exact match*) o milisegundos (semántico), frente a segundos de una llamada.
- **Coste:** cada *cache hit* es una llamada que no pagas.
- **Fiabilidad:** una respuesta en caché no depende del proveedor. Si OpenAI se cae pero está cacheada, tu sistema sigue funcionando para esas consultas.

### Cacheo en LLMs vs cacheo web tradicional

En web la clave es **determinista**: `GET /api/users/42` siempre devuelve lo mismo — la clave *es* la URL. En LLMs el *input* rara vez es idéntico: *"¿Cómo reseteo mi contraseña?"*, *"¿proceso para recuperar la contraseña?"* y *"olvidé mi password, ¿qué hago?"* son la misma pregunta con tres formulaciones. De ahí **tres capas**, de simple a sofisticada:

1. **Exact match:** comparación exacta del *input*. Rápido (microsegundos), simple, solo para inputs idénticos.
2. **Cacheo semántico:** convierte el *input* en un *embedding* y busca consultas de **significado similar**. Más lento (ms), pero captura reformulaciones.
3. **Prompt caching del proveedor:** mecanismo nativo de algunos proveedores (Anthropic, OpenAI) que cachea porciones del *prompt* entre llamadas. No cachea la respuesta completa, sino que abarata procesar la parte repetida del *prompt*.

> **Embedding** = representación numérica (vector) del significado de un texto.
> **Similitud coseno** = medida de cuán parecidos son dos vectores; base del cacheo semántico.

### Exact match — el punto de partida

Es lo que se implementa en vivo y lo **correcto para nuestro caso**: transcripciones idénticas deben dar la misma estimación. La clave: generar una **clave de caché determinista** a partir de **todos** los parámetros que afectan a la respuesta (no basta el *prompt* — si cambia el modelo o la *temperature*, la respuesta cambia).

```python
def _cache_key(self, prompt, model, system_prompt):
    raw = json.dumps({"prompt": prompt, "model": model, "system_prompt": system_prompt}, sort_keys=True)
    return f"llm:{hashlib.sha256(raw.encode()).hexdigest()}"
# completion(): mirar caché (redis.get) → si hit, marcar cache_hit=True y devolver;
# si miss, llamar al LLM, guardar con setex(key, ttl, ...) y devolver.
```

Que el `system_prompt` forme parte de la clave importa: nuestro *system prompt* incluye los ejemplos que alimentan el CAG. Si cambiamos esos ejemplos, **las claves cambian solas y las entradas antiguas expiran por TTL** — invalidación implícita, sin borrar la caché a mano.

> **TTL** (*Time To Live*) = tiempo que una entrada de caché vive antes de expirar. Es la decisión más importante: para el estimador, 24 h es razonable; para datos en tiempo real (bolsa, pedidos), minutos.

### Cacheo semántico — capturar reformulaciones

El *exact match* falla con un espacio extra o una frase introductoria distinta. El semántico compara el **significado**: convierte la *query* en vector, busca uno almacenado con **similitud coseno** por encima de un umbral y devuelve la respuesta; si no, llama al LLM y guarda vector + respuesta.

> El **umbral de similitud es el parámetro crítico**: demasiado alto (0.99) y casi no hay *hits*; demasiado bajo (0.85) y devuelves respuestas incorrectas. Punto de partida recomendado: **0.95**, ajustando con datos reales.

> La implementación de ejemplo guarda *embeddings* en memoria con búsqueda lineal — vale para prototipos, **no escala**. En producción los *embeddings* van a una **base de datos vectorial** (pgvector, Qdrant, Pinecone) con búsqueda aproximada por vecinos más cercanos en milisegundos aunque haya millones de entradas. Es el tema central de las **sesiones 07 y 08**.

### Cacheo multi-nivel — combinar estrategias

La mejor arquitectura combina ambas: *exact match* como primera línea (rápida y barata) y semántico como segunda (más lento, más *hits*).

1. Llega una *query*. ¿Está en *exact match*? → sí: devolver (microsegundos).
2. *Miss*. ¿Hay una semánticamente similar? → sí: devolver (ms) y **promoverla a *exact match*** para futuras consultas idénticas.
3. Ambas fallan. Llamar al LLM y guardar en las dos cachés.

Mismo patrón que el hardware (L1/L2/L3) y la web (CDN → Redis → BD): las capas rápidas atrapan los casos fáciles, las sofisticadas capturan el resto.

### Cuándo cachear y cuándo no

- **Cachea cuando:** los *inputs* se repiten (FAQs, transcripciones ya procesadas); la respuesta no necesita ser única (estimaciones, resúmenes); el coste/latencia importan; los datos cambian poco.
- **No caches cuando:** cada respuesta debe ser única (generación creativa, *brainstorming*); los datos cambian constantemente (precios, inventario); el contexto del usuario es crítico y varía; la *temperature* es alta (>0.7) y esperas variabilidad.

Para el Proyecto 1, el *exact match* es claramente apropiado: misma transcripción + mismo contexto CAG = misma estimación. Es una tarea determinista donde la **repetibilidad es deseable**.

### Invalidación — el problema difícil

> *"Solo hay dos problemas difíciles en informática: la invalidación de caché, nombrar cosas, y los errores off-by-one."*

> **Invalidar** = decidir cuándo una entrada de caché ya no es válida.

Tres estrategias:
- **TTL:** la más simple; cada entrada expira tras un tiempo fijo (24 h FAQs, 1 h info de producto, 5 min datos semi-dinámicos). La opción por defecto.
- **Invalidación por evento:** cuando cambian los datos fuente, borras las entradas asociadas (con *tags* o *namespaces*). Si actualizamos los ejemplos del CAG, invalidaríamos toda la caché.
- **Versionado del prompt:** incluir una versión del *system prompt* en la clave; al cambiarlo, las claves difieren y lo antiguo expira por TTL. Es lo que hace nuestro `_cache_key`.

> En la práctica, **TTL + versionado del prompt** basta para la mayoría de apps.

### Métricas — qué medir

Cachear sin medir es adivinar. Métricas fundamentales:
- **Hit rate:** % de *requests* servidas desde caché. <20 % apenas justifica la infra; >50 % el ahorro es significativo.
- **Latencia hit vs miss:** la diferencia debería ser de **100-1000x**.
- **Coste evitado:** tokens no consumidos, traducidos a dinero.
- **Tasa de *stale responses*:** con qué frecuencia devuelves respuestas ya incorrectas. Si es alta, el TTL es demasiado largo o la invalidación insuficiente.

> En vivo implementamos **exact match con Redis** sobre el *wrapper*. El cacheo semántico se deja como concepto: requiere *embeddings* y búsqueda vectorial (sesiones 07-08).

---

## 4. Streaming y manejo de respuestas largas

### El problema

Con una transcripción larga, el usuario pulsa enviar, ve un *spinner* 5-10 segundos y, de golpe, aparece todo el texto. Durante esos segundos **no hay feedback**: no sabe si procesa, se colgó o perdió conexión. Es el comportamiento por defecto de una API REST: el servidor genera la respuesta completa y solo la envía al terminar.

> El **streaming** envía la respuesta **fragmento a fragmento, según el LLM la genera** (como ChatGPT o Claude). El tiempo total es el mismo, pero **el primer token llega en milisegundos** y puedes empezar a leer mientras se genera el resto.

### Tres mecanismos, un objetivo

**StreamingResponse (*chunked transfer*)** — el más básico
> **StreamingResponse / chunked transfer** = FastAPI envía la respuesta con el *header* `Transfer-Encoding: chunked` (no `Content-Length`): "no sé cuánto mide, te voy mandando trozos". El servidor genera *chunks* con un **generador async**.

```python
async def generate_estimation(transcription):
    stream = client.chat.completions.create(model="gpt-4o-mini", messages=[...], stream=True)
    for chunk in stream:
        if chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content

@app.post("/estimate")
async def estimate(transcription: str):
    return StreamingResponse(generate_estimation(transcription), media_type="text/plain")
```
La clave es `stream=True`. **Cuándo usarlo:** datos crudos (texto plano, archivos grandes, audio/vídeo) sin necesidad de estructura. Es el de menor *overhead*.

**Server-Sent Events (SSE)** — el recomendado para LLMs en web
> **SSE** = un nivel por encima: en vez de *bytes* crudos, envía **eventos estructurados** con campos (`data`, `event`, `id`, `retry`). El navegador tiene API nativa (`EventSource`).

Añade **estructura y resiliencia**: cada evento puede tener tipo e identificador, y si la conexión se corta el navegador **reconecta solo** y envía el último `id`, permitiendo retomar. Desde FastAPI 0.135.0 hay soporte nativo (`EventSourceResponse`, `ServerSentEvent`).

```python
@app.post("/estimate/stream", response_class=EventSourceResponse)
async def estimate_stream(transcription: str):
    stream = client.chat.completions.create(model="gpt-4o-mini", messages=[...], stream=True)
    for chunk in stream:
        if chunk.choices[0].delta.content:
            yield ServerSentEvent(data=chunk.choices[0].delta.content)
```
El cliente es más limpio (`new EventSource(...)`, `onmessage`, `onerror`): gestiona conexión, parseo y reconexión sin bucle manual. **Es el estándar de facto** que usan OpenAI y Anthropic en sus APIs de *streaming*.

**WebSockets** — comunicación bidireccional
> **WebSocket** = canal **bidireccional persistente** cliente↔servidor (los dos anteriores son unidireccionales servidor→cliente). Empieza con un *handshake* HTTP (`Upgrade: websocket`, respuesta `101 Switching Protocols`) y luego abandona HTTP.

Es lo que hace un chat (escribes, responde, escribes de nuevo). Pero son **mucho más complejos** de implementar, testear y escalar: necesitan gestión de conexiones, no tienen reconexión automática y no van bien con *load balancers* sin *sticky sessions*.

### Cuál usar para nuestro proyecto

- **En Streamlit:** no implementas nada. `st.write_stream()` acepta el *stream* del SDK de OpenAI/Anthropic y lo renderiza token a token. Por eso el ejercicio pre-sesión lo pide: resuelve el *streaming* de UI **sin tocar HTTP**.
- **En el endpoint FastAPI (clientes que no sean Streamlit):** **SSE** — eventos estructurados, reconexión automática, implementación limpia. Es lo que integramos en vivo.
- **WebSockets:** para más adelante, cuando las apps de chat necesiten bidireccionalidad real (un agente que pide aclaraciones durante una tarea larga).

### Streaming con distintos proveedores

Cada SDK lo hace algo distinto: **OpenAI** devuelve objetos `ChatCompletionChunk` (`chunk.choices[0].delta.content`); **Anthropic** usa un *context manager* y eventos `text` (`with client.messages.stream(...) as stream: for text in stream.text_stream`).

> Esta diferencia es **otro argumento a favor de la capa de abstracción**: con LiteLLM la interfaz de *streaming* es uniforme (sigue la convención de OpenAI para todos) — cambias el modelo en configuración y el código de *streaming* no se toca.

### Manejo de respuestas largas

Los modelos tienen un límite de tokens de salida (`max_tokens` / `max_completion_tokens`). Si la estimación lo excede, **se corta a mitad de frase** — y una estimación incompleta puede ser peor que ninguna. Estrategias:

- **Configurar `max_tokens` explícitamente** con margen. Si las estimaciones típicas son 500-800 tokens, `max_tokens=2000` da holgura. **Solo pagas los tokens generados**, así que un máximo alto no cuesta más si la respuesta real es corta.
- **Detectar truncamiento con `finish_reason`.** Si vale `"length"` (en vez de `"stop"`), se cortó por el límite: puedes pedir continuación o avisar.

  > **finish_reason** = campo que indica si la respuesta terminó (`stop`) o se truncó (`length`).
- **Diseñar el *prompt* para controlar la longitud** ("estimación concisa de máximo 500 palabras"). No es garantía (los modelos no cuentan palabras con precisión) pero reduce desbordes.

Para el Proyecto 1, un `max_tokens` generoso + detección de `finish_reason` basta. Estrategias más sofisticadas (dividir la generación, resumen progresivo) se ven en el módulo de RAG avanzado.

> En vivo integramos *streaming* en el *wrapper*: Streamlit → *wrapper* → comprueba caché → si no, llama al LLM con `stream=True` → tokens a Streamlit vía `st.write_stream`. Además montamos un endpoint **SSE** en FastAPI para clientes externos.

---

## 5. Observabilidad, *logging* y trazabilidad

### El problema

Vienes de web con un hábito razonable: registrar errores, *requests* HTTP y algún evento de negocio. Con LLMs ese *logging* es **ciego**. Sabes que `/estimate` respondió 200 en 4.2 s. Lo que **no** sabes: qué *prompt* se envió, cuántos tokens consumió, cuánto costó, qué modelo respondió (¿OpenAI o el *fallback*?), si vino de caché, ni por qué la estimación tiene calidad dudosa.

> En apps clásicas el comportamiento es **determinista**. El LLM es una **caja negra probabilística**: puede dar respuestas distintas al mismo *prompt*. Depurar esto sin trazabilidad es trabajar a ciegas.

La trazabilidad para LLMs necesita tres dimensiones que el *logging* web no contempla:
- **Qué se envió y recibió:** *prompt* completo (system + user), respuesta literal, parámetros (modelo, *temperature*, `max_tokens`).
- **Cuánto costó:** tokens entrada/salida, modelo, coste. Sin esto, un *bug* en el *prompt* que genera respuestas larguísimas puede **multiplicar tu factura** antes de que lo notes.
- **Qué camino siguió:** ¿caché? ¿*fallback*? ¿cuántos reintentos? ¿cuánto tardó cada fase?

### Structured logging — la base

> **Structured logging** = registrar logs como **objetos con campos tipados** (JSON), parseables por máquinas, en vez de texto plano (`"LLM call completed in 3.2s"`).

```json
{
  "timestamp": "2026-04-02T10:30:15.123Z", "level": "info", "event": "llm_call_completed",
  "model": "gpt-4o-mini", "provider": "openai", "tokens_in": 1847, "tokens_out": 423,
  "cost_usd": 0.00089, "latency_ms": 3215, "cache_hit": false, "fallback_used": false
}
```

Misma información que el texto plano, pero ahora puedes **filtrar por modelo, agregar costes por periodo, detectar picos de latencia y calcular el *hit rate*** programáticamente, sin parsear *strings* con regex.

### Structlog — la librería que usaremos

> **Structlog** = la librería de *structured logging* más madura de Python (en producción desde 2013). Filosofía: *los logs son datos, no strings*.

La idea clave es la **cadena de procesadores** (`processors`): cada uno recibe el diccionario del evento, lo enriquece y lo pasa al siguiente (`add_log_level`, `TimeStamper`, `EventRenamer`...). El último es siempre el *renderer*: **`JSONRenderer` en producción, `ConsoleRenderer` en desarrollo**.

> Esta **configuración dual** (consola bonita en *dev*, JSON en *prod*) es un patrón casi universal: en desarrollo quieres leer logs rápido en el terminal; en producción los ingieren Elasticsearch, Loki, CloudWatch... y todos esperan JSON.

### Contexto vinculado al *logger* (`bind`)

Structlog permite **vincular datos contextuales** a un *logger* con `bind()`, evitando repetir campos:
```python
request_logger = logger.bind(request_id="req-abc-123", endpoint="/estimate")
# Todos los logs de esta request llevan request_id y endpoint automáticamente
request_logger.info("llm_call_started", model="gpt-4o-mini")
```
En FastAPI, el `bind` se haría en un **middleware** que asigna un `request_id` único a cada *request*.

### Qué registrar en cada llamada al LLM

- **Al inicio:** modelo solicitado, proveedor destino, tokens de entrada, si se resuelve desde caché.
- **Al completar:** tokens de salida, latencia total (ms), coste estimado (USD), `finish_reason`, si hubo *fallback* y a qué proveedor.
- **En caso de error:** tipo de error (*timeout*, *rate limit*, *auth*, *server*), proveedor que falló, si se intentará *fallback*, número de reintento.

El patrón —*log* al inicio, al completar y en error— es el mismo que para *requests* HTTP o *queries* de BD; cambian los campos (tokens y costes en vez de *status codes* y *row counts*).

### Más allá del *logging*: herramientas de observabilidad

El *structured logging* da la materia prima; las herramientas de observabilidad la convierten en información accionable (*dashboards*, alertas, trazas visuales, análisis de costes). Dos categorías:

**Full-stack** (trazan toda la app *y* entienden la capa LLM):
> **Pydantic Logfire** *(la más relevante para nuestro stack)* = herramienta del equipo de Pydantic, construida sobre **OpenTelemetry**.

Ofrece trazas unificadas (una *timeline* con la *request* HTTP, la caché Redis, la llamada al LLM y la respuesta), paneles para LLMs (conversación system/user/assistant, *token tracking*), monitorización de costes con alertas, integración nativa con FastAPI/OpenAI/Anthropic/LiteLLM/Redis (una línea cada una) y consulta de trazas con **SQL** (PostgreSQL-compatible). *Free tier* de 10M *spans*/mes, de sobra para el proyecto.

> **OpenTelemetry** = estándar abierto de observabilidad (trazas, métricas, logs).
> **Span** = unidad de trabajo medida dentro de una traza.

**Específicas para LLMs** (solo ven la capa de IA: *prompts*, respuestas, cadenas de razonamiento):
- **LangSmith** (equipo de LangChain) — referencia para inspeccionar el razonamiento de agentes paso a paso. Integración automática si usas LangChain/LangGraph; si **no** los usas, pierde gran parte de su valor.
- **Langfuse** — la alternativa **open source** más completa (licencia MIT, auto-hosteable, vía OpenTelemetry o SDK propio). *Tracing*, gestión de *prompts*, evaluaciones y *datasets*. Sólida con requisitos de privacidad.
- **Helicone** — mención por su **simplicidad radical**: cambias una *base URL* en tu cliente de OpenAI y se activa todo el *logging*. La ruta más rápida si tu prioridad es velocidad de *setup*.

### Cuál elegir

- **Structlog** para *logging* local — lo de la sesión en vivo, sin dependencias externas.
- **Logfire** para observabilidad visual — integración nativa con nuestro stack (Pydantic + FastAPI + OpenAI/Anthropic).
- **Langfuse** si necesitas open source auto-hosteable (privacidad).
- **LangSmith** si ya usas LangChain — se ve en los módulos de agentes (sesiones 12-14).

> No necesitas todas a la vez. **Empieza con structlog** (la base) y añade una herramienta visual cuando el volumen haga insostenible depurar leyendo logs en el terminal. Los logs JSON de structlog son **directamente ingeribles** por todas ellas.

---

## Cómo encaja todo en el Proyecto 1 (síntesis)

Las cinco piezas convergen en **un único *wrapper* de abstracción** que envuelve la llamada al LLM. El flujo completo que se construye en la sesión:

```
┌─────────────────────────┐
│   Interfaz Streamlit     │  (§1 — ejercicio pre-sesión; st.write_stream para streaming de UI)
│   (sesión 03)            │
└───────────┬─────────────┘
            │
┌───────────▼─────────────┐
│   Endpoint FastAPI       │  (sesión 02; endpoint SSE para clientes externos, §4)
└───────────┬─────────────┘
            │
┌───────────▼─────────────┐
│   LLM Wrapper            │  ← lo que se construye en el directo
│   • Abstracción (§2)     │     una sola interfaz; el proveedor es configuración
│   • Fallback (§2)        │     rota de proveedor sin que el usuario lo note
│   • Caché exact-match(§3)│     Redis; no pagar dos veces lo mismo
│   • Streaming (§4)       │     stream=True; tokens progresivos
│   • Logging (§5)         │     structlog; modelo, tokens, coste, latencia, resultado
└───────────┬─────────────┘
            │
   ┌────────┴────────┐
   ▼                 ▼
┌────────┐      ┌───────────┐
│ OpenAI │      │ Anthropic │
└────────┘      └───────────┘
```

El endpoint llama al *wrapper*; el *wrapper* decide proveedor, comprueba caché, hace *streaming* y registra todo. El endpoint **no sabe ni le importa** qué proveedor respondió: recibe una respuesta normalizada y sigue con su parseo y validación.

> Cada decisión de diseño apunta a lo mismo: **desacoplar la lógica de negocio de los detalles del proveedor** y **hacer el sistema observable y económico** en producción.

El ejercicio pre-sesión conecta Streamlit **directamente** al LLM (sin *wrapper*) — momento pedagógico deliberado: primero experimentas el acoplamiento directo y sus problemas, y luego lo resolvéis juntos refactorizando esa conexión para que pase por el *wrapper*.

---

## Chuleta rápida

| Pieza | Problema | Herramienta de la sesión | Clave |
|---|---|---|---|
| **Interfaz** | Probar sin `curl` | **Streamlit** (pre-sesión) | `st.write_stream`; *Gradio* para demos, *Chainlit* para chat serio |
| **Abstracción + fallback** | Acoplamiento a un proveedor | **LiteLLM** (`Router`) | El proveedor es configuración; `fallbacks` + `num_retries` |
| **Cacheo** | Pagar dos veces lo mismo | **Redis exact-match** | Clave determinista (prompt+model+system); TTL 24 h |
| **Streaming** | *Spinner* sin feedback | **SSE** (FastAPI) / `st.write_stream` (UI) | `stream=True`; detectar `finish_reason="length"` |
| **Observabilidad** | *Logging* ciego para LLMs | **structlog** | Log al inicio/fin/error: modelo, tokens, coste, latencia, caché, fallback |

**Números a recordar:**
- Cacheo semántico: **40-70 %** de aciertos con tráfico real; umbral de similitud por defecto **0.95**; TTL exact-match **24 h**.
- `max_tokens=2000` para estimaciones de 500-800 tokens; solo pagas lo generado.
- LiteLLM **1.82.7 / 1.82.8** comprometidas (marzo 2026) → fijar versiones.
- Latencia hit vs miss debería ser **100-1000x**; *hit rate* útil >50 %.

**La meta-lección:** las cinco piezas no son temas sueltos — convergen en un único *wrapper* que **desacopla la lógica de negocio del proveedor** y hace el sistema **observable y económico**. La diferencia entre "funciona en mi máquina" y "funciona en producción" está ahí.

---

## Cómo conecta con nuestro ejercicio

- **El ejercicio pre-sesión** conecta Streamlit directo al LLM (sin *wrapper*) — pedagógico a propósito: experimentas el acoplamiento antes de resolverlo. El directo refactoriza esa conexión para que pase por el *wrapper*.
- **La caché semántica** que aquí solo se menciona necesita *embeddings* y búsqueda vectorial — se desarrolla en las **sesiones 07 y 08** (pgvector), ver `docs/session-08-datadrivenai-bbdd-vectoriales/`.
- **El *routing* por complejidad** y la observabilidad de agentes (LangSmith) son la semilla de los **módulos de orquestación de agentes** (sesiones 12-14).
- **Nuestro stack** (Pydantic + FastAPI + OpenAI/Anthropic) hace de **Logfire** la opción natural de observabilidad visual cuando structlog se quede corto.

---

## Referencias por bloque

**1. Interfaces conversacionales**
- ATNO for GenAI — *"Streamlit vs Gradio vs Chainlit: Building Quick UIs for Your AI Applications"* (Medium, marzo 2026)
- Streamlit Docs — *"Build a basic LLM chat app"*

**2. Abstracción de proveedores y fallback**
- ProxAI — *"The LLM Abstraction Layer: Why Your Codebase Needs One in 2025"* (sept. 2025) · `https://www.proxai.co/blog/archive/llm-abstraction-layer`
- LiteLLM — Documentación oficial: *Getting Started, Router* (`docs.litellm.ai`)

**3. Cacheo inteligente**
- Reintech — *"LLM Caching Strategies: Reduce Response Times by 80-95%"* (enero 2026)
- AI Echoes — *"Benchmarking LLM Exact and Semantic Caching with Redis"* (marzo 2026)
- Redis Blog — *"What is Semantic Caching?"* (enero 2026)

**4. Streaming y respuestas largas**
- Hassaan Bin Aslam — *"Streaming Responses in FastAPI"* (enero 2025)
- FastAPI Docs — *"Server-Sent Events (SSE)"*
- Sevalla — *"Real-time OpenAI Response Streaming with FastAPI"* (noviembre 2025)

**5. Observabilidad, logging y trazabilidad**
- Better Stack — *"A Comprehensive Guide to Python Logging with Structlog"* (enero 2026)
- Pydantic Logfire — *"AI & LLM Observability"* (documentación oficial)
- Firecrawl — *"Best LLM Observability Tools in 2026"* (diciembre 2025)

---

*Versión clara de la teoría de la Sesión 3 · AI Engineering 2026/04. La búsqueda vectorial y pgvector que aquí solo se mencionan se desarrollan en las sesiones 7 y 8 (`docs/session-08-datadrivenai-bbdd-vectoriales/session-08-theory-datadrivenai-bbdd-vectoriales.md`).*
