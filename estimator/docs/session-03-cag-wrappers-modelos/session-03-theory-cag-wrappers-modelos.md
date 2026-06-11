# Sesión 3 — Teoría: de un endpoint que funciona a un sistema de producción

> Resumen único de la teoría de la Sesión 3 del curso **AI Engineering 2026/04** (autor de los
> artículos: Antonio Pérez). Reúne y ordena los cinco bloques de teoría:
> **1)** interfaces conversacionales, **2)** abstracción de proveedores y *fallback*,
> **3)** cacheo inteligente, **4)** *streaming* y respuestas largas, y **5)** observabilidad y *logging*.
>
> Documento de estudio: cada apartado abre con una introducción en lenguaje llano (para entender
> *por qué* importa) y después entra en el detalle técnico.

---

## El hilo conductor de la sesión

En la sesión 2 construimos algo que **funciona**: un endpoint FastAPI que recibe la transcripción de
una reunión y devuelve una estimación de software usando CAG (*Context-Augmented Generation*). Pero
"funciona en mi máquina" y "funciona en producción" son dos cosas distintas.

Esta sesión trata de todo lo que rodea a ese endpoint para convertirlo en un **producto serio**.
Piensa en la diferencia entre un coche que arranca y un coche con cinturón, airbag, cuadro de mandos
y rueda de repuesto: el motor es el mismo, pero todo lo que lo envuelve es lo que lo hace usable y
fiable. En IA esa "carrocería" tiene cinco piezas:

| Pieza | Problema que resuelve | Pregunta humana |
|-------|----------------------|-----------------|
| **Interfaz** | Que alguien que no sea programador pueda usarlo | "¿Cómo lo prueba un *project manager*?" |
| **Abstracción + fallback** | No depender de un solo proveedor de LLM | "¿Y si OpenAI se cae o sube precios?" |
| **Cacheo** | No pagar dos veces por la misma respuesta | "¿Por qué pagar de nuevo si la pregunta es idéntica?" |
| **Streaming** | Que el usuario vea la respuesta mientras se genera | "¿Por qué miro un *spinner* 8 segundos?" |
| **Observabilidad** | Saber qué pasó cuando algo falla | "¿Qué prompt se envió y cuánto costó?" |

Casi todo lo que veremos se construye sobre una idea central: un **wrapper** (envoltorio) que se
coloca entre el endpoint y los proveedores de LLM, y que concentra abstracción, *fallback*, caché,
*streaming* y *logging*. Lo montamos a lo largo de la sesión en vivo.

---

## 1. Interfaces conversacionales: Streamlit, Gradio y Chainlit

### Introducción para humanos

Tienes un endpoint que recibe texto y devuelve una respuesta de un LLM. Funciona, pero la única forma
de probarlo es con `curl`, Postman o Swagger — herramientas de programador. Si quieres que lo use una
persona no técnica, o simplemente tener una experiencia de chat decente mientras desarrollas,
necesitas una **interfaz web**.

Construirla desde cero con HTML/CSS/JavaScript es posible, pero arrastra mucho trabajo repetitivo:
gestionar el estado de la conversación, pintar el texto en *streaming*, manejar la entrada, mostrar
indicadores de carga... Toda esa "fontanería" ya está resuelta. Los *frameworks* de interfaz para IA
permiten crear una UI funcional **en Python puro**, sin escribir JavaScript, muchas veces en menos de
50 líneas.

Hay tres opciones dominantes, y cada una nació con un propósito distinto — eso explica sus fortalezas
y límites.

### Streamlit — el generalista

No nació para chatbots, sino como herramienta para *dashboards* y apps de datos. Con el tiempo añadió
elementos de chat (`st.chat_message`, `st.chat_input`), pero su ADN sigue siendo el de una herramienta
de propósito general.

El concepto **más importante** a entender es su modelo de ejecución: *cada vez que el usuario
interactúa, Streamlit re-ejecuta todo el script de arriba a abajo*. Esto simplifica el desarrollo (el
código se lee como un guion secuencial), pero obliga a usar `st.session_state` para **persistir
cualquier dato** entre interacciones — incluido el historial de la conversación.

Un chat funcional con *streaming* se reduce a ~25 líneas; `st.write_stream` recibe el *stream* del SDK
y lo renderiza progresivamente, sin manipular *chunks* a mano.

- **Fortalezas:** la mayor comunidad, el ecosistema de componentes más rico (gráficos, tablas, mapas,
  *file uploads*, *sidebars*), soporte nativo *multipage* y *deployment* gratuito en Streamlit
  Community Cloud. Si la app necesita **algo más que chat**, es la opción más natural.
- **Limitaciones:** el modelo de re-ejecución completa complica el estado complejo; no hay procesos en
  *background*, ni *websockets* persistentes, ni actualizaciones en tiempo real sin *workarounds*.
  Personalizar CSS es luchar contra el *framework*. Para chat en producción con autenticación,
  persistencia y gestión de hilos, se queda corto.

### Gradio — la demo rápida

Nació en el ecosistema de Hugging Face con un propósito muy concreto: **envolver cualquier función
Python en una interfaz web** para demos de modelos de ML. Su filosofía es `input → función → output`.
Para chat ofrece `gr.ChatInterface`.

- **Fortalezas:** la ruta más rápida de "tengo una función Python" a "tengo una demo web compartible".
  `demo.launch(share=True)` genera una **URL pública temporal (72 h)** sin *deployment* — ideal para
  enseñar un prototipo a un *stakeholder* en 5 minutos. Integración con Hugging Face Spaces para demos
  permanentes. Componentes **multimodales** nativos (imagen, audio, vídeo) que los demás no ofrecen.
- **Limitaciones:** la gestión de estado es más limitada (`gr.State` funciona pero es menos intuitivo
  que `session_state`); *layouts* multipágina no nativos. Para chat en producción con autenticación,
  persistencia e hilos, se queda sin capacidades.

### Chainlit — el especialista en chat

Es el más joven y el más especializado. No es una herramienta de *dashboards* ni de demos de ML: se
diseñó **exclusivamente** como capa de UI para aplicaciones conversacionales con LLMs (chatbots,
agentes, asistentes).

Esa especialización se nota: trae de serie lo que en Streamlit/Gradio hay que implementar a mano —
*streaming* nativo, *threading* de mensajes, visualización paso a paso del razonamiento del agente,
recolección de *feedback*, autenticación y persistencia de conversaciones. Está construido sobre
`asyncio` desde su base (`async def`), lo que hace el *streaming* y la concurrencia naturales.

- **Fortalezas:** la **observabilidad integrada** es su rasgo diferencial — puedes ver la "cadena de
  pensamiento" del agente (qué *prompt* se envió, qué herramientas usó, qué devolvió cada paso),
  indispensable para depurar agentes complejos. Integración nativa con LangChain y LlamaIndex.
  Autenticación con Azure AD, Google y otros. Persistencia *out-of-the-box*.
- **Limitaciones:** su foco exclusivo en chat lo hace incómodo para UI no conversacional. La librería
  de componentes es mucho más pequeña (sin gráficos, *dataframes* ni mapas nativos). Comunidad más
  reducida (menos ejemplos) y documentación aún con asperezas.

### ¿Y construirlo desde cero?

La cuarta opción es no usar *framework* y conectar HTML/CSS/JS directamente a tu backend FastAPI.
Tiene sentido cuando necesitas **control total** de la UX, cuando el chat es solo un componente dentro
de una app web mayor, o cuando el diseño es incompatible con los *frameworks*. Ventaja: control
absoluto. Desventaja: implementar tú mismo estado, renderizado, *streaming* (con SSE o WebSockets),
indicadores de carga... toda la fontanería que los *frameworks* dan gratis. Para producción con
requisitos de UX específicos suele ser la mejor opción a largo plazo; para prototipar, los
*frameworks* ahorran tiempo.

### Tabla comparativa

| Criterio | Streamlit | Gradio | Chainlit |
|----------|-----------|--------|----------|
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

**Regla práctica:** *Streamlit* si necesitas más que chat o prototipar rápido (es el del ejercicio
pre-sesión); *Gradio* para demos rápidas y multimodales; *Chainlit* para una app de chat seria con
agentes y observabilidad.

---

## 2. Abstracción de proveedores y estrategias de *fallback*

### Introducción para humanos

El estimador de la sesión 2 funciona, pero tiene un problema serio si lo miramos con honestidad: está
**acoplado a un único proveedor**. Si usas el SDK de OpenAI, tu código importa `openai`, llama a
`client.chat.completions.create()` y parsea la respuesta con la estructura específica de OpenAI. El día
que quieras probar Claude no basta con cambiar una variable: hay que reescribir la llamada, adaptar el
parseo, manejar errores distintos y ajustar el conteo de tokens.

Esto no es teórico. En el ecosistema actual: **los proveedores se caen** (OpenAI y Anthropic han
tenido incidentes documentados), **los precios cambian**, **aparecen modelos mejores cada trimestre**
y **las APIs evolucionan** (parámetros nuevos, formatos distintos, endpoints deprecados).

La industria ya resolvió esto antes. Hace una década el desarrollo web dejó de escribir SQL a mano y
adoptó **ORMs** (SQLAlchemy, Prisma, ActiveRecord): una capa de abstracción entre la lógica de negocio
y la base de datos, para cambiar de MySQL a PostgreSQL sin reescribir la aplicación. **Lo que un ORM
hace para bases de datos, una capa de abstracción de LLMs lo hace para modelos de lenguaje.**

### Qué es una capa de abstracción de LLMs

Una interfaz unificada entre tu código y los proveedores. En lugar de llamar al SDK de cada uno, llamas
a una función genérica (p. ej. `completion()`) y la capa traduce esa llamada al formato del proveedor
configurado. El contrato es simple: tu lógica de negocio habla **un solo idioma**, y el *wrapper*
traduce a tantos proveedores como necesites.

```python
# Acoplado a OpenAI
from openai import OpenAI
client = OpenAI()
response = client.chat.completions.create(model="gpt-4o-mini", messages=[...])

# Desacoplado: el proveedor es configuración, no código
from litellm import completion
response = completion(model="gpt-4o-mini", messages=[...])  # cambiar a "claude-haiku-4-5" = 0 cambios
```

El cambio parece menor, pero la implicación es enorme: **cambiar de proveedor pasa a ser un cambio de
configuración**, no de código. Tu lógica de negocio (el *system prompt*, el parseo, la validación) no
se toca.

### ¿Construir tu propio *wrapper* o usar uno existente?

La pregunta natural de un desarrollador senior: "¿no puedo escribir yo mi propio *wrapper*?". Sí, y al
principio parece lo más limpio. El problema es que esa clase **crece rápido**. Los problemas reales de
mantener un *wrapper* ad-hoc en producción:

- **Mantenimiento continuo:** cada cambio de API de un proveedor obliga a actualizar el *wrapper*. Con
  dos proveedores es manejable; con cinco, es un trabajo a tiempo parcial.
- **Re-implementar lo ya resuelto:** reintentos con *backoff* exponencial, conteo de tokens por modelo,
  gestión de *rate limits*, normalización de respuestas entre proveedores, manejo de errores por SDK.
- **Casos borde no anticipados:** *timeouts* parciales, respuestas truncadas, errores intermitentes de
  red, cambios silenciosos en APIs — aparecen en producción, no en desarrollo. Un open source con miles
  de usuarios ya los ha visto; tu *wrapper* casero no.
- **El coste real:** el tiempo mantenido en el *wrapper* es tiempo que no inviertes en el producto.

Un *wrapper* propio solo tiene sentido cuando tu necesidad es muy específica y ninguna herramienta la
cubre bien. En la mayoría de proyectos reales, la abstracción merece la pena.

### Herramientas disponibles

**LiteLLM — el agregador ligero** *(la que usaremos)*
Librería Python open source con interfaz compatible para **+100 modelos de +10 proveedores**. Su
filosofía es ser ligera: no impone *chains*, *agents* ni *pipelines*, solo estandariza la llamada. Más
allá de la abstracción ofrece:
- *Router* con *fallback* y reintentos (lista de modelos por prioridad; si el primero falla, intenta el
  siguiente; *backoff* configurable).
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

> ⚠️ **Nota de seguridad de dependencias:** en marzo de 2026 las versiones **1.82.7 y 1.82.8 de LiteLLM
> en PyPI fueron comprometidas con código malicioso**. Se detectó y bloqueó rápido, pero es un
> recordatorio real del riesgo de dependencias en Python. Buena práctica: **fijar versiones** en
> `pyproject.toml` y verificar *hashes*. Aplica a cualquier dependencia, no solo a LiteLLM.

**OpenRouter — el marketplace**
Funciona como un mercado de modelos: una sola *API key* y accedes a decenas de modelos vía una API
unificada; OpenRouter gestiona *routing*, facturación consolidada y balanceo opcional. Ventaja:
simplicidad operativa (una cuenta, una factura). Desventaja: **tus datos pasan por sus servidores**
(problema de *compliance*) y aplican un margen sobre el precio original. Útil para prototipos y
explorar modelos; para producción con datos sensibles, la mayoría prefiere llamar directo con una capa
local como LiteLLM.

**LangChain — el framework completo**
Ofrece abstracción de proveedores como parte de un *framework* mucho mayor (*chains*, *agents*,
memoria, *tools*). Para el propósito concreto de abstraer + *fallback* está **sobredimensionado** ("usar
Rails para servir una página estática"). Brilla en orquestación compleja — eso llega en los módulos 4 y
5. Para esta sesión, LiteLLM es la herramienta correcta por su menor complejidad.

### Estrategias de *fallback*

La abstracción habilita una capacidad fundamental de producción: el ***fallback* automático**. Si un
proveedor falla, el sistema rota al siguiente **sin intervención manual y sin que el usuario lo note**.

- **Fallback secuencial (el más común):** lista ordenada de proveedores. Intenta el primero; si falla
  (*timeout*, error 500, *rate limit*) pasa al segundo, etc. El orden refleja tu preferencia
  (primero el más barato/rápido). Es lo que configura el *Router* de LiteLLM, y lo que usa la mayoría.
- **Fallback por tipo de error:** no todos los errores merecen *fallback*. Un error de autenticación
  (*API key* inválida) no se arregla reintentando. Un *timeout* sí justifica reintento. Un 429
  (*rate limit*) justifica esperar y reintentar, o rotar.

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
- **Routing por complejidad (avanzado):** enrutar según la dificultad de la tarea. Transcripciones
  cortas → modelo económico (`gpt-4o-mini`, `claude-haiku-4-5`); transcripciones complejas → modelo
  potente (`gpt-4o`, `claude-sonnet-4-6`). No es exactamente *fallback* sino *routing* inteligente, pero
  comparte la filosofía de **desacoplar la elección del modelo de la lógica de negocio**. Se ve en las
  sesiones de orquestación de agentes.

### Criterios para elegir herramienta

- **Privacidad de datos:** ¿pueden pasar por terceros? Si no (*compliance*, GDPR, datos sensibles),
  descarta OpenRouter y cualquier *proxy* externo. LiteLLM y *wrappers* propios mantienen las llamadas
  directas.
- **Complejidad de la app:** solo abstracción + *fallback* → LiteLLM; orquestación de agentes →
  LangChain; *marketplace* con factura consolidada → OpenRouter.
- **Overhead operativo:** LiteLLM como librería es `pip install` + una línea; como *proxy* requiere
  infraestructura; LangChain implica aprender un *framework*.
- **Madurez:** LiteLLM tiene +40 000 estrellas en GitHub y es dependencia transitiva de muchos
  *frameworks* de agentes; todas las opciones son maduras a estas alturas.

> **Idea clave:** la abstracción de proveedores **no es un lujo arquitectónico — es un requisito** para
> cualquier sistema con LLMs que aspire a producción. El coste de implementarla es mínimo; el coste de
> no tenerla aparece el día que tu proveedor se cae, sube precios o deprecia tu modelo.

---

## 3. Cacheo inteligente de respuestas de LLMs

### Introducción para humanos

Imagina que un *project manager* pega la **misma transcripción dos veces** (porque quiere revisar la
estimación de ayer, o cerró la pestaña por error). Sin caché, el sistema hace dos llamadas al LLM, paga
los tokens dos veces y el usuario espera dos veces los 3-5 segundos de latencia — para obtener una
respuesta prácticamente idéntica. Hemos quemado dinero y tiempo para regenerar lo mismo.

No es un caso excepcional: las apps reales con LLMs muestran **repetición constante** (los chatbots de
soporte reciben las mismas preguntas, etc.). Según datos de producción de 2026, el cacheo semántico
alcanza tasas de acierto del **40-70 %** con tráfico real. Tres beneficios directos:

- **Latencia:** respuesta cacheada en microsegundos (*exact match*) o milisegundos (semántico), frente
  a segundos de una llamada al LLM.
- **Coste:** cada *cache hit* es una llamada que no pagas.
- **Fiabilidad:** una respuesta en caché no depende de la disponibilidad del proveedor. Si OpenAI se
  cae pero la respuesta está cacheada, tu sistema sigue funcionando para esas consultas.

### Cacheo en LLMs vs cacheo web tradicional

Si vienes de web ya conoces Redis, Memcached, CDN. El concepto es el mismo, pero hay una diferencia que
cambia las estrategias. En web la clave es **determinista**: `GET /api/users/42` siempre devuelve lo
mismo — la clave *es* la URL. En LLMs el *input* del usuario rara vez es idéntico: *"¿Cómo reseteo mi
contraseña?"*, *"¿Cuál es el proceso para recuperar la contraseña?"* y *"He olvidado mi password, ¿qué
hago?"* son la misma pregunta con tres formulaciones. Esto da **tres capas** de cacheo, de simple a
sofisticada:

1. **Exact match:** comparación exacta del *input*. Rápido (microsegundos), simple, pero solo para
   inputs idénticos.
2. **Cacheo semántico:** convierte el *input* en un *embedding* y busca consultas de **significado
   similar**. Más lento (ms) pero captura reformulaciones.
3. **Prompt caching del proveedor:** mecanismo nativo de algunos proveedores (Anthropic, OpenAI) que
   cachea porciones del *prompt* entre llamadas. No cachea la respuesta completa, sino que reduce el
   coste de procesar la parte repetida del *prompt*.

### Exact match — el punto de partida

Es la estrategia que se implementa en vivo y la **correcta para nuestro caso**: transcripciones
idénticas deben producir la misma estimación. La clave: generar una **clave de caché determinista** a
partir de **todos** los parámetros que afectan a la respuesta (no basta con el *prompt* — si cambia el
modelo o la *temperature*, la respuesta cambia).

```python
def _cache_key(self, prompt, model, system_prompt):
    raw = json.dumps({"prompt": prompt, "model": model, "system_prompt": system_prompt}, sort_keys=True)
    return f"llm:{hashlib.sha256(raw.encode()).hexdigest()}"
# completion(): mirar caché (redis.get) → si hit, marcar cache_hit=True y devolver;
# si miss, llamar al LLM, guardar con setex(key, ttl, ...) y devolver.
```

Que el `system_prompt` forme parte de la clave es importante: nuestro *system prompt* incluye las
estimaciones de ejemplo que alimentan el CAG. Si cambiamos esos ejemplos, **las claves cambian solas y
las entradas antiguas expiran por TTL** — invalidación implícita, sin borrar la caché a mano.

El **TTL (*Time To Live*)** es la decisión más importante: para el estimador, 24 h es razonable (las
transcripciones y las estimaciones de ejemplo no cambian a menudo). Para datos en tiempo real (precios
de bolsa, estado de pedidos) el TTL debería ser de minutos.

### Cacheo semántico — capturar reformulaciones

El *exact match* falla con un espacio extra o una frase introductoria distinta. El cacheo semántico
compara el **significado**: convierte la *query* en un vector, busca un vector almacenado con
**similitud coseno** por encima de un umbral y devuelve la respuesta asociada; si no, llama al LLM y
guarda vector + respuesta.

El **umbral de similitud es el parámetro crítico**: demasiado alto (0.99) y casi no habrá *hits*;
demasiado bajo (0.85) y devolverás respuestas incorrectas (consultas parecidas con intenciones
distintas tratadas como iguales). Punto de partida recomendado: **0.95**, ajustando con datos reales.

> La implementación de ejemplo guarda *embeddings* en memoria con búsqueda lineal — vale para
> prototipos, **no escala**. En producción los *embeddings* van a una **base de datos vectorial**
> (pgvector, Qdrant, Pinecone) con búsqueda aproximada por vecinos más cercanos en milisegundos aunque
> haya millones de entradas. Esto es el tema central de las **sesiones 07 y 08** del módulo Data-driven
> AI.

### Cacheo multi-nivel — combinar estrategias

La mejor arquitectura combina ambas capas: *exact match* como primera línea (rápida y barata) y
semántico como segunda (más lento, más *hits*).

1. Llega una *query*. ¿Está en *exact match*? → sí: devolver (microsegundos).
2. *Miss*. ¿Hay una semánticamente similar? → sí: devolver (ms) y **promoverla a *exact match*** para
   futuras consultas idénticas.
3. Ambas fallan. Llamar al LLM y guardar en las dos cachés.

Es el mismo patrón que el hardware (L1/L2/L3 en CPUs) y la infraestructura web (CDN → Redis → BD): las
capas rápidas atrapan los casos fáciles, las sofisticadas capturan el resto.

### Cuándo cachear y cuándo no

**Cachea cuando:** los *inputs* se repiten (FAQs, transcripciones ya procesadas); la respuesta no
necesita ser única (estimaciones, resúmenes, respuestas factuales); el coste/latencia importan; los
datos cambian poco.
**No caches cuando:** cada respuesta debe ser única (generación creativa, *brainstorming*); los datos
cambian constantemente (precios, inventario); el contexto del usuario es crítico y varía; la
*temperature* es alta (>0.7) y esperas variabilidad.

Para el Proyecto 1, el *exact match* es claramente apropiado: una misma transcripción con el mismo
contexto CAG produce la misma estimación. No hay creatividad — es una tarea determinista donde la
**repetibilidad es deseable**.

### Invalidación — el problema difícil

> *"Solo hay dos problemas difíciles en informática: la invalidación de caché, nombrar cosas, y los
> errores off-by-one."*

Invalidar es decidir cuándo una entrada ya no es válida. Tres estrategias:
- **TTL:** la más simple; cada entrada expira tras un tiempo fijo (24 h FAQs, 1 h info de producto,
  5 min datos semi-dinámicos). La opción por defecto.
- **Invalidación por evento:** cuando cambian los datos fuente, borras las entradas asociadas (con
  *tags* o *namespaces*). En nuestro proyecto, si actualizamos las estimaciones de ejemplo del CAG,
  deberíamos invalidar toda la caché.
- **Versionado del prompt:** incluir una versión del *system prompt* en la clave; al cambiarlo, las
  claves difieren y lo antiguo expira por TTL. Es lo que hace nuestro `_cache_key`.

En la práctica, **TTL + versionado del prompt** basta para la mayoría de apps.

### Métricas — qué medir

Cachear sin medir es "optimizar sin *profiling*": adivinar. Métricas fundamentales:
- **Hit rate:** % de *requests* servidas desde caché. <20 % apenas justifica la infra; >50 % el ahorro
  es significativo.
- **Latencia hit vs miss:** la diferencia debería ser de **100-1000x**.
- **Coste evitado:** tokens no consumidos, traducidos a dinero.
- **Tasa de *stale responses*:** con qué frecuencia devuelves respuestas ya incorrectas. Si es alta, el
  TTL es demasiado largo o la invalidación insuficiente.

> En vivo implementamos **exact match con Redis** sobre el *wrapper*. El cacheo semántico se deja como
> concepto: su implementación real requiere *embeddings* y búsqueda vectorial (sesiones 07-08).

---

## 4. Streaming y manejo de respuestas largas

### Introducción para humanos

Cuando el estimador recibe una transcripción larga, el usuario vive esto: pulsa enviar, ve un *spinner*
5-10 segundos y, de golpe, aparece un bloque de texto completo. Durante esos segundos **no hay feedback
visual**: no sabe si el sistema procesa, se ha colgado o ha perdido conexión.

Es el comportamiento por defecto de una API REST: el servidor genera la respuesta completa y solo la
envía cuando termina. El **streaming** lo resuelve enviando la respuesta **fragmento a fragmento, a
medida que el LLM la genera**. El usuario ve el texto "escribiéndose" en tiempo real (como ChatGPT o
Claude). El tiempo total es el mismo, pero **recibe el primer token en milisegundos** en lugar de
esperar al último — y puede empezar a leer el resumen mientras se genera el detalle.

### Tres mecanismos, un objetivo

Para enviar datos del servidor al cliente de forma progresiva hay tres mecanismos HTTP, cada uno a un
nivel distinto:

**StreamingResponse (*chunked transfer*)** — el más básico
FastAPI envía la respuesta con el *header* `Transfer-Encoding: chunked` en lugar de `Content-Length`
("no sé cuánto mide, te voy enviando trozos"). El servidor genera *chunks* con un **generador async** y
el cliente los lee con `response.body.getReader()`.
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
La clave es `stream=True`. **Cuándo usarlo:** datos crudos (texto plano, archivos grandes, audio/vídeo)
sin necesidad de estructura. Es el de menor *overhead*.

**Server-Sent Events (SSE)** — el recomendado para LLMs en web
Opera un nivel por encima: en vez de *bytes* crudos, envía **eventos estructurados** con campos
definidos (`data`, `event`, `id`, `retry`). El navegador tiene una API nativa (`EventSource`). Añade
**estructura y resiliencia**: cada evento puede tener tipo e identificador, y si la conexión se corta el
navegador **reconecta solo** y envía el último `id`, permitiendo al servidor retomar. Desde FastAPI
0.135.0 hay soporte nativo (`EventSourceResponse`, `ServerSentEvent`).
```python
@app.post("/estimate/stream", response_class=EventSourceResponse)
async def estimate_stream(transcription: str):
    stream = client.chat.completions.create(model="gpt-4o-mini", messages=[...], stream=True)
    for chunk in stream:
        if chunk.choices[0].delta.content:
            yield ServerSentEvent(data=chunk.choices[0].delta.content)
```
El cliente es más limpio (`new EventSource(...)`, `onmessage`, `onerror`): `EventSource` gestiona
conexión, parseo y reconexión, sin bucle manual. **Es el estándar de facto** que usan OpenAI y Anthropic
en sus propias APIs de *streaming*.

**WebSockets** — comunicación bidireccional
Protocolo completamente distinto: mientras StreamingResponse y SSE son **unidireccionales**
(servidor → cliente), los WebSockets abren un **canal bidireccional persistente**. Empieza con un
*handshake* HTTP (`Upgrade: websocket`, respuesta `101 Switching Protocols`) y luego abandona HTTP. Es
exactamente lo que hace un chat (el usuario escribe, el servidor responde, el usuario escribe de nuevo).
Pero son **mucho más complejos** de implementar, testear y escalar: necesitan gestión de conexiones, no
tienen reconexión automática y no funcionan bien con *load balancers* sin *sticky sessions*.

### Cuál usar para nuestro proyecto

- **En Streamlit:** no implementas nada a mano. `st.write_stream()` acepta directamente el *stream* del
  SDK de OpenAI/Anthropic y lo renderiza token a token. Por eso el ejercicio pre-sesión pide usarlo:
  resuelve el *streaming* de UI **sin tocar HTTP**.
- **En el endpoint FastAPI (clientes que no sean Streamlit):** **SSE** es la opción correcta — eventos
  estructurados, reconexión automática, implementación limpia. Es lo que integramos en vivo.
- **WebSockets:** reservados para más adelante, cuando las apps de chat necesiten bidireccionalidad real
  (p. ej. un agente que pide aclaraciones al usuario durante una tarea larga).

### Streaming con distintos proveedores

Cada SDK implementa el *streaming* de forma ligeramente distinta. **OpenAI** devuelve objetos
`ChatCompletionChunk` (`chunk.choices[0].delta.content`). **Anthropic** usa un *context manager* y
eventos de tipo `text` (`with client.messages.stream(...) as stream: for text in stream.text_stream`).
Esta diferencia es **otro argumento a favor de la capa de abstracción**: con LiteLLM la interfaz de
*streaming* es uniforme (sigue la convención de OpenAI para todos los proveedores) — cambias el modelo
en configuración y el código de *streaming* no se toca.

### Manejo de respuestas largas

El *streaming* resuelve la UX, pero queda otro problema: **¿qué pasa si la respuesta es demasiado
larga?** Los modelos tienen un límite de tokens de salida (`max_tokens` / `max_completion_tokens`). Si
la estimación lo excede, la respuesta **se corta a mitad de frase** — y una estimación incompleta puede
ser peor que ninguna. Estrategias:

- **Configurar `max_tokens` explícitamente** con margen. Si las estimaciones típicas son de 500-800
  tokens, `max_tokens=2000` da holgura. **Solo pagas los tokens que se generan**, así que un máximo alto
  no cuesta más si la respuesta real es corta.
- **Detectar truncamiento con `finish_reason`.** Si vale `"length"` (en vez de `"stop"`), se cortó por
  el límite: puedes pedir continuación o avisar al usuario.
- **Diseñar el *prompt* para controlar la longitud** ("genera una estimación concisa de máximo 500
  palabras"). No es garantía (los modelos no cuentan palabras con precisión) pero reduce los desbordes.

Para el Proyecto 1, un `max_tokens` generoso + detección de `finish_reason` es suficiente. Estrategias
más sofisticadas (dividir la generación, resumen progresivo) se ven en el módulo de RAG avanzado.

> En vivo integramos *streaming* en el *wrapper*: Streamlit → *wrapper* → comprueba caché → si no, llama
> al LLM con `stream=True` → los tokens se envían a Streamlit vía `st.write_stream`. Además montamos un
> endpoint **SSE** en FastAPI para clientes externos.

---

## 5. Observabilidad, *logging* y trazabilidad

### Introducción para humanos

Vienes de web con un hábito razonable: registrar errores, *requests* HTTP y algún evento de negocio. Con
eso, si algo falla, reconstruyes qué pasó. Con LLMs, ese nivel de *logging* es **ciego**. Sabes que
`/estimate` respondió 200 en 4.2 s. Lo que **no** sabes: qué *prompt* se envió exactamente, cuántos
tokens consumió, cuánto costó, qué modelo respondió (¿OpenAI o el *fallback* a Anthropic?), si la
respuesta vino de caché, ni por qué la estimación tiene calidad dudosa.

En apps clásicas, el comportamiento es **determinista**. Con LLMs, el modelo es una **caja negra
probabilística**: puede devolver respuestas distintas para el mismo *prompt*, y su calidad depende de
factores que no controlas directamente. Depurar esto sin trazabilidad es trabajar a ciegas. La
trazabilidad para LLMs necesita cubrir tres dimensiones que el *logging* web no contempla:

- **Qué se envió y qué se recibió:** *prompt* completo (system + user), respuesta literal, parámetros
  (modelo, *temperature*, `max_tokens`).
- **Cuánto costó:** tokens de entrada/salida, modelo, coste calculado. Sin esto, un *bug* en el *prompt*
  que genera respuestas larguísimas puede **multiplicar tu factura** antes de que lo notes.
- **Qué camino siguió la llamada:** ¿caché? ¿*fallback*? ¿cuántos reintentos? ¿cuánto tardó cada fase?

### Structured logging — la base

El primer paso (y el que implementamos en vivo) es el ***structured logging***. No es específico de
LLMs, pero es el cimiento de todo lo demás. En lugar de registrar texto plano (`"LLM call completed in
3.2s"`), registramos **objetos estructurados con campos tipados**, parseables por máquinas:

```json
{
  "timestamp": "2026-04-02T10:30:15.123Z", "level": "info", "event": "llm_call_completed",
  "model": "gpt-4o-mini", "provider": "openai", "tokens_in": 1847, "tokens_out": 423,
  "cost_usd": 0.00089, "latency_ms": 3215, "cache_hit": false, "fallback_used": false
}
```

Misma información que el texto plano, pero ahora puedes **filtrar por modelo, agregar costes por
periodo, detectar picos de latencia y calcular el *hit rate*** — todo programáticamente, sin parsear
*strings* con regex.

### Structlog — la librería que usaremos

La librería de *structured logging* más madura de Python (en producción desde 2013). Su filosofía: *los
logs son datos, no strings*. La idea clave es la **cadena de procesadores** (`processors`): cada uno
recibe el diccionario del evento, lo enriquece y lo pasa al siguiente (`add_log_level`, `TimeStamper`,
`EventRenamer`...). El último siempre es el *renderer*: **`JSONRenderer` en producción, `ConsoleRenderer`
en desarrollo**.

Esta **configuración dual** (consola bonita en *dev*, JSON en *prod*) es un patrón que usarás en casi
todo proyecto: en desarrollo quieres leer logs rápido en el terminal; en producción quieres que los
ingieran Elasticsearch, Loki, CloudWatch... y todos esperan JSON.

### Contexto vinculado al *logger* (`bind`)

Structlog permite **vincular datos contextuales** a un *logger* con `bind()`, evitando repetir campos:
```python
request_logger = logger.bind(request_id="req-abc-123", endpoint="/estimate")
# Todos los logs de esta request llevan request_id y endpoint automáticamente
request_logger.info("llm_call_started", model="gpt-4o-mini")
```
En una app FastAPI, el `bind` se haría en un **middleware** que asigna un `request_id` único a cada
*request* entrante.

### Qué registrar en cada llamada al LLM

- **Al inicio:** modelo solicitado, proveedor destino, tokens de entrada, si se resuelve desde caché.
- **Al completar:** tokens de salida, latencia total (ms), coste estimado (USD), `finish_reason`
  (¿completó o se truncó?), si hubo *fallback* y a qué proveedor.
- **En caso de error:** tipo de error (*timeout*, *rate limit*, *auth*, *server*), proveedor que falló,
  si se intentará *fallback*, número de reintento.

El patrón —*log* al inicio, al completar y en error— es el mismo que para trazar *requests* HTTP o
*queries* de BD; lo que cambia son los campos (tokens y costes en vez de *status codes* y *row counts*).

### Más allá del *logging*: herramientas de observabilidad

El *structured logging* da la materia prima; las herramientas de observabilidad la convierten en
información accionable (*dashboards*, alertas, trazas visuales, análisis de costes). Dos categorías:

**Full-stack** (trazan toda la app *y* entienden la capa LLM):
- **Pydantic Logfire** — *la más relevante para nuestro stack*. Construida por el equipo de Pydantic
  (la librería de validación de FastAPI) y sobre **OpenTelemetry**. Ofrece trazas unificadas (una
  *timeline* con la *request* HTTP, la caché en Redis, la llamada al LLM y la respuesta), paneles para
  LLMs (conversación system/user/assistant, *token tracking*), monitorización de costes con alertas,
  integración nativa con FastAPI/OpenAI/Anthropic/LiteLLM/Redis (una línea cada una) y consulta de
  trazas con **SQL** (PostgreSQL-compatible). *Free tier* de 10M *spans*/mes, de sobra para el proyecto.

**Específicas para LLMs** (solo ven la capa de IA: *prompts*, respuestas, cadenas de razonamiento):
- **LangSmith** (equipo de LangChain) — referencia para inspeccionar el razonamiento de agentes paso a
  paso. Integración automática si usas LangChain/LangGraph; si **no** los usas, pierde gran parte de su
  valor.
- **Langfuse** — la alternativa **open source** más completa (licencia MIT, auto-hosteable, vía
  OpenTelemetry o SDK propio). *Tracing*, gestión de *prompts*, evaluaciones y *datasets*. Sólida si
  tienes requisitos de privacidad.
- **Helicone** — mención por su **simplicidad radical**: cambias una *base URL* en tu cliente de OpenAI
  y se activa todo el *logging*. La ruta más rápida si tu prioridad es velocidad de *setup*.

### Cuál elegir

- **Structlog** para *logging* local — lo de la sesión en vivo, sin dependencias externas.
- **Logfire** si quieres observabilidad visual — integración nativa con nuestro *stack* (Pydantic +
  FastAPI + OpenAI/Anthropic).
- **Langfuse** si necesitas open source auto-hosteable (privacidad).
- **LangSmith** si ya usas LangChain — se ve en los módulos de agentes (sesiones 12-14).

> No necesitas todas a la vez. **Empieza con structlog** (la base) y añade una herramienta visual cuando
> el volumen haga insostenible depurar leyendo logs en el terminal. Los logs JSON de structlog son
> **directamente ingeribles** por todas ellas.

---

## Cómo encaja todo en el Proyecto 1 (síntesis)

Las cinco piezas no son temas sueltos: convergen en **un único *wrapper* de abstracción** que envuelve
la llamada al LLM. El flujo completo que se construye a lo largo de la sesión:

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

El endpoint llama al *wrapper*; el *wrapper* decide proveedor, comprueba caché, hace *streaming* y
registra todo. El endpoint **no sabe ni le importa** qué proveedor respondió: recibe una respuesta
normalizada y sigue con su parseo y validación. Cada decisión de diseño de la sesión apunta a lo mismo:
**desacoplar la lógica de negocio de los detalles del proveedor** y **hacer el sistema observable y
económico** en producción.

El ejercicio pre-sesión conecta Streamlit **directamente** al LLM (sin *wrapper*) — es un momento
pedagógico deliberado: primero experimentas el acoplamiento directo y sus problemas, y luego lo
resolvéis juntos en el directo refactorizando esa conexión para que pase por el *wrapper*.

---

## Glosario rápido

| Término | En una frase |
|---------|--------------|
| **CAG** (*Context-Augmented Generation*) | Inyectar contexto/ejemplos en el *prompt* para guiar al modelo. |
| **Wrapper / capa de abstracción** | Código intermedio que unifica el acceso a varios proveedores de LLM. |
| **Fallback** | Rotar automáticamente a otro proveedor cuando el primero falla. |
| **Embedding** | Representación numérica (vector) del significado de un texto. |
| **Similitud coseno** | Medida de cuán parecidos son dos vectores; base del cacheo semántico. |
| **TTL** (*Time To Live*) | Tiempo que una entrada de caché vive antes de expirar. |
| **Streaming** | Enviar la respuesta por fragmentos según se genera, no de golpe. |
| **SSE** (*Server-Sent Events*) | Protocolo unidireccional de eventos estructurados servidor→cliente. |
| **WebSocket** | Canal bidireccional persistente entre cliente y servidor. |
| **finish_reason** | Campo que indica si la respuesta terminó (`stop`) o se truncó (`length`). |
| **Structured logging** | Registrar logs como objetos (JSON) en vez de texto plano. |
| **OpenTelemetry** | Estándar abierto de observabilidad (trazas, métricas, logs). |
| **Span** | Unidad de trabajo medida dentro de una traza distribuida. |

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

*Documento de teoría de la Sesión 3 · AI Engineering 2026/04. Relacionado: la búsqueda vectorial y
pgvector que aquí solo se mencionan se desarrollan en la teoría de las sesiones 7 y 8
(`docs/session-08-rag-bbdd-vectoriales/session-08-theory-rag-bbdd-vectoriales.md`).*
