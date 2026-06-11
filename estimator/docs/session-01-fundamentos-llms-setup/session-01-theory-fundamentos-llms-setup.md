# Sesión 1 — Teoría: APIs de LLMs, parámetros, tokenización y comparación de modelos

> Este documento resume **los seis artículos teóricos** de la Sesión 1 en un único texto, en
> orden:
>
> 1. **Estructura de una llamada al API de OpenAI** (Responses API vs Chat Completions).
> 2. **Estructura de una llamada al API de Anthropic** (Messages API).
> 3. **Estructura de una llamada al API de Gemini** (Google Gen AI SDK).
> 4. **Parámetros en modelos de razonamiento** (qué se bloquea y qué lo reemplaza).
> 5. **Tokenización: conceptos avanzados** (de texto a números, coste y límites).
> 6. **Comparación de modelos 2026** (proveedores, precios y elección por caso de uso).
>
> Cada parte empieza, cuando hace falta, con una **explicación para cualquiera** (sin tecnicismos)
> antes de bajar al detalle técnico. El hilo conductor de toda la sesión es uno: **una llamada a un
> LLM es siempre la misma idea —instrucciones + entrada + configuración → respuesta + metadatos—,
> y lo que cambia entre proveedores es el envoltorio, no el concepto.**

---

## 0. La idea en una página (para cualquiera)

Un **modelo de lenguaje** (LLM) es un programa que recibe texto y devuelve texto. No "entiende" como
una persona: predice qué fragmento de texto viene a continuación, una y otra vez, hasta completar una
respuesta. Para usarlo desde nuestro código llamamos a un **API**: enviamos una petición por internet
al servidor del proveedor (OpenAI, Anthropic, Google…) y recibimos la respuesta.

Toda llamada, da igual el proveedor, tiene **tres ingredientes de entrada**:

1. **Las instrucciones del sistema** ("eres un experto en estimación de proyectos, responde en
   español, sé conciso"). Las pone el desarrollador y el usuario final no las ve. Es el "carácter"
   del asistente.
2. **La entrada del usuario** (la pregunta concreta). Es lo único que cambia en cada interacción.
3. **La configuración** (qué modelo usar, cuánta creatividad permitir, cuánto puede extenderse la
   respuesta…).

Y devuelve **dos cosas**: el **texto de respuesta** y unos **metadatos** (cuántos "tokens" se han
gastado, qué modelo exacto respondió, si terminó bien o se cortó…).

Tres conceptos atraviesan toda la sesión y conviene tenerlos claros desde el principio:

- **Token**: la unidad mínima en la que el modelo trocea el texto. No es ni una letra ni una palabra,
  sino algo intermedio. **Todo se factura por tokens**, así que los tokens son dinero.
- **Sin memoria (stateless)**: el modelo **no recuerda** la conversación anterior. Si quieres que
  "recuerde", tienes que reenviarle todo el historial en cada llamada. Esto hace que las
  conversaciones largas sean cada vez más caras.
- **Modelos de razonamiento**: una generación nueva de modelos que "piensan" antes de responder.
  A cambio de más calidad, pierdes control sobre algunos ajustes y ese "pensamiento" se factura
  aunque no lo veas.

El resto del documento es, esencialmente, esta misma idea contada con precisión para los tres
grandes proveedores, más dos capítulos transversales (tokenización y comparación de modelos).

---

# PARTE 1 — Estructura de una llamada al API de OpenAI

## 1.1 Dos APIs, una recomendación

OpenAI ofrece hoy **dos APIs** para generar texto:

- **Responses API** (`client.responses.create`) — La más reciente y **la recomendada para todo
  proyecto nuevo**. Lanzada en marzo de 2025, unifica las capacidades de las anteriores (Chat
  Completions y Assistants) en una interfaz más limpia. Incluye soporte nativo de herramientas
  integradas (búsqueda web, búsqueda en archivos, ejecución de código), gestión de estado entre
  turnos y mejor rendimiento con modelos de razonamiento.
- **Chat Completions API** (`client.chat.completions.create`) — La anterior, soportada
  indefinidamente pero ya no recomendada para desarrollos nuevos. Su estructura de `messages` con
  roles (`system`, `user`, `assistant`) **es el patrón que comparten la mayoría de proveedores
  alternativos** (Anthropic, Google, Mistral), por lo que sigue siendo relevante entenderla.

> **En el programa usamos la Responses API como API principal.** Chat Completions aparecerá cuando
> trabajemos con otros proveedores o con agregadores como LiteLLM.

## 1.2 La llamada completa

```python
from openai import OpenAI

client = OpenAI()  # Lee OPENAI_API_KEY del entorno

response = client.responses.create(
    model="gpt-4o-mini",
    instructions="You are a software project estimation expert. You respond...",
    input="What factors should I consider when estimating a database migration?",
    temperature=0.7,
    max_output_tokens=500,
)

print(response.output_text)
```

Diferencias clave respecto a Chat Completions: las instrucciones del sistema van en un parámetro
**dedicado** (`instructions`, no como un mensaje más), la entrada del usuario va en `input` (un
string directo o un array de mensajes), y accedes al texto con **`response.output_text`** en lugar
de navegar por `choices[0].message.content`.

## 1.3 `instructions`: rol, instrucciones y restricciones

`instructions` cumple la función del *system prompt*: define **cómo se comportará el modelo** durante
toda la interacción. Es un parámetro de primer nivel, separado de los mensajes. Tiene tres
componentes típicos:

- **Rol** — Quién es el modelo ("You are a senior software project estimation consultant"). Fija el
  nivel de conocimiento y el marco de referencia.
- **Instrucciones operativas** — Qué debe hacer y cómo ("responde en español", "usa terminología
  técnica", "incluye un rango de estimación").
- **Restricciones** — Qué **no** debe hacer ("no inventes datos", "sin bullet points", "pregunta
  antes de adivinar"). Son tan importantes como las instrucciones: definen los límites.

**Por qué importa la separación:** en un producto real, el desarrollador define `instructions` (fijo
o semi-fijo) y el usuario aporta `input` (variable). Esa separación es la base de la arquitectura
**CAG** que construimos en el programa: el usuario no necesita saber que hay un prompt detrás.

## 1.4 `input`: estructura de mensajes

Acepta dos formatos:

- **String simple** — para interacciones de un solo turno: `input="What is a REST API?"`.
- **Array de mensajes con roles** — para conversaciones multi-turno o más control. Roles:
  - `user` — mensajes del usuario humano.
  - `assistant` — respuestas previas del modelo (se incluyen para dar contexto).
  - `developer` — instrucciones del desarrollador intercaladas (equivalente al antiguo `system` de
    Chat Completions, pero integrado en el flujo). Las `instructions` de primer nivel tienen
    prioridad sobre estas.

## 1.5 Conversación multi-turno

El modelo **no mantiene estado**: cada llamada es independiente. Dos opciones para gestionar el
contexto:

- **Opción A — Manual:** incluyes todo el historial en el array de `input` en cada llamada (igual que
  en Chat Completions).
- **Opción B — `previous_response_id`** (exclusivo de Responses API): pasas el ID de la respuesta
  anterior y OpenAI recupera el contexto por ti. Requiere `store=True`. Simplifica el código y mejora
  la utilización de caché (menos tokens de entrada repetidos = menos coste). **Contrapartida:** estás
  almacenando datos en servidores de OpenAI; para requisitos de privacidad estrictos, la opción
  manual puede ser preferible.

## 1.6 Parámetros de configuración

| Parámetro | Para qué sirve |
|---|---|
| `model` | Qué modelo usar. En el programa, `gpt-4o-mini` por su relación calidad/precio. |
| `temperature` | Aleatoriedad. `0.0` = determinista (siempre el token más probable). Para análisis/estimación, `0.0`–`0.3`; para tareas creativas, `0.7`–`1.0`. |
| `max_output_tokens` | Techo de tokens de salida. Si la respuesta natural lo supera, se corta y `status` será `"incomplete"` (con `incomplete_details`). **No** es el número de tokens que usará, solo el límite. |
| `store` | Si OpenAI almacena la respuesta. Necesario para `previous_response_id`. Por defecto `True`; ponlo a `False` con datos sensibles. |
| `top_p` | Alternativa a `temperature` (núcleo de probabilidad). **Usa uno u otro, nunca ambos.** |
| `reasoning` | Exclusivo de modelos de razonamiento (`o3`, `o4-mini`…). Controla cuánto "piensa" antes de responder. |
| `tools` | Herramientas nativas: `web_search_preview`, `file_search`, `code_interpreter`, `computer_use`. Ventaja significativa sobre Chat Completions. |

## 1.7 Estructura de la respuesta

El objeto devuelto tiene varios niveles. Lo esencial:

- `output_text` — atajo directo al texto generado.
- `output` — array de Items tipados (mensajes, tool calls…). Para casos con herramientas iteras
  sobre él.
- `status` — `"completed"` (terminó bien), `"incomplete"` (se cortó; mira `incomplete_details`) o
  `"failed"` (error; mira `error`).
- `id` — identificador (`resp_...`); doble uso: trazabilidad/logs y encadenar turnos con
  `previous_response_id`.
- `model` — el **snapshot exacto** usado, no el alias. Pides `"gpt-4o-mini"` y puedes recibir
  `"gpt-4o-mini-2024-07-18"`. Relevante porque OpenAI actualiza modelos periódicamente.
- `created_at` — timestamp Unix de creación.
- `usage` — `input_tokens`, `output_tokens`, `total_tokens` y `output_tokens_details.reasoning_tokens`.

## 1.8 Tokens y coste

- **Tokens de entrada** — todo lo que envías: `instructions` + historial + última entrada. En
  conversaciones largas crece turno a turno.
- **Tokens de salida** — lo que genera el modelo. Más caros (entre 2x y 5x según el modelo).
- **Tokens de razonamiento** — en modelos con razonamiento, los tokens del "pensamiento" interno. Se
  facturan **como tokens de salida** aunque no aparezcan en la respuesta visible.

```python
# gpt-4o-mini: precio por 1M de tokens
INPUT_PRICE = 0.15
OUTPUT_PRICE = 0.60
input_cost = (response.usage.input_tokens / 1_000_000) * INPUT_PRICE
output_cost = (response.usage.output_tokens / 1_000_000) * OUTPUT_PRICE
```

Para una llamada típica con `gpt-4o-mini`, el coste ronda $0.0001–$0.0005 (fracciones de centavo).
Es despreciable por llamada, pero a escala (miles de usuarios, conversaciones largas) se convierte en
un factor de diseño. Además, la Responses API tiene **mejor utilización de caché** que Chat
Completions (entre un 40% y un 80% de mejora según OpenAI).

## 1.9 Manejo de errores

El SDK lanza excepciones tipadas:

- `AuthenticationError` (401) — API key inválida, expirada o ausente. El error más común al empezar.
- `RateLimitError` (429) — superado el límite de llamadas/tokens por minuto, **o** crédito
  insuficiente. Solución: esperar y reintentar, o añadir crédito.
- `BadRequestError` (400) — modelo incorrecto, mensajes mal formados o parámetro fuera de rango. Lee
  el mensaje: suele ser descriptivo.
- `APIConnectionError` — no se puede conectar (red local, firewall, caída temporal).
- `InternalServerError` (500) — error del lado de OpenAI. Reintenta tras unos segundos.

Para errores transitorios, el patrón estándar es **reintento con espera exponencial** (1s, 2s, 4s…).
Este patrón lo evolucionamos en la Sesión 3 al construir la capa de abstracción de proveedores con
estrategias de *fallback*.

## 1.10 Equivalencia Responses ↔ Chat Completions

| Concepto | Responses API | Chat Completions API |
|---|---|---|
| Instrucciones del sistema | `instructions="..."` | `messages=[{"role":"system",...}]` |
| Entrada del usuario | `input="..."` o `input=[...]` | `messages=[{"role":"user",...}]` |
| Texto de respuesta | `response.output_text` | `response.choices[0].message.content` |
| Límite de tokens | `max_output_tokens` | `max_tokens` |
| Tokens de entrada | `usage.input_tokens` | `usage.prompt_tokens` |
| Tokens de salida | `usage.output_tokens` | `usage.completion_tokens` |
| Estado | `response.status` | `response.choices[0].finish_reason` |
| Encadenar conversación | `previous_response_id` | Reconstruir array manualmente |
| Herramientas integradas | `tools=[{"type":"web_search_preview"}]` | No disponible nativamente |
| Almacenamiento | `store=True/False` | No aplica (siempre stateless) |

---

# PARTE 2 — Estructura de una llamada al API de Anthropic

## 2.1 Una sola API: Messages

Anthropic ofrece una **única API**: la **Messages API** (`client.messages.create`). A diferencia de
OpenAI (dos APIs en paralelo), Anthropic ha consolidado toda su funcionalidad aquí desde el
lanzamiento. Sigue un patrón similar al de Chat Completions —envías un array de mensajes con roles y
recibes una respuesta estructurada— pero con diferencias importantes: el *system prompt* va en un
parámetro separado (como en la Responses API), la estructura de la respuesta cambia, y
**`max_tokens` es obligatorio** (en OpenAI es opcional).

## 2.2 La llamada completa

```python
from anthropic import Anthropic

client = Anthropic()  # Lee ANTHROPIC_API_KEY del entorno

response = client.messages.create(
    model="claude-haiku-4-5-20251001",
    system="You are a software project estimation expert. You respond...",
    messages=[
        {"role": "user", "content": "What factors should I consider..."},
    ],
    max_tokens=500,
    temperature=0.7,
)

print(response.content[0].text)
```

Diferencias clave respecto a OpenAI: el *system prompt* va en el parámetro `system` (no dentro del
array de `messages`), `max_tokens` es **obligatorio** (Anthropic no asume un valor por defecto), y
accedes al texto con **`content[0].text`**.

## 2.3 `system`: el system prompt como parámetro separado

Funciona conceptualmente igual que `instructions` de OpenAI. Acepta un **string simple** o un
**array de bloques de contenido** (el array es útil para combinar texto con `cache_control` →
*prompt caching*, una funcionalidad avanzada). Para los ejercicios, el string simple basta. La misma
lógica de separación que en OpenAI: el desarrollador define `system`, el usuario aporta `messages`.

## 2.4 `messages`: la regla de alternancia

El array de `messages` representa la conversación. Cada mensaje tiene `role` y `content`. Roles:
`user` y `assistant`. **A diferencia de OpenAI, Anthropic NO tiene un rol `system` dentro del array**
— las instrucciones van siempre en el parámetro `system`.

**Regla de alternancia:** los mensajes deben **alternar estrictamente** `user` → `assistant` →
`user`. El primer mensaje debe ser siempre de `user`. No puedes poner dos mensajes consecutivos del
mismo rol.

```python
# ❌ INCORRECTO: dos mensajes user consecutivos
messages=[{"role":"user","content":"Hello"}, {"role":"user","content":"How are you?"}]

# ✅ CORRECTO: alterna user → assistant → user
messages=[
    {"role":"user","content":"Hello"},
    {"role":"assistant","content":"Hi! How can I help you?"},
    {"role":"user","content":"How are you?"},
]
```

Si necesitas enviar varias piezas de información del usuario en un solo turno, combínalas en un único
mensaje o usa *content blocks*.

## 2.5 Conversación multi-turno

La Messages API es **stateless**. **No hay equivalente a `previous_response_id`** — la gestión del
historial es siempre manual. Te da control total sobre qué contexto envías, pero gestionas el array
en tu código. Implicación directa en coste: cada turno reenvía **todo el historial** como tokens de
entrada, y el coste por llamada crece. Anthropic lo mitiga con su **prompt caching** (hasta un 90% de
descuento en *cache hits*).

## 2.6 Parámetros de configuración

| Parámetro | Notas |
|---|---|
| `model` | `claude-haiku-4-5-20251001` en el programa. Los IDs **incluyen la fecha del snapshot** (a diferencia de OpenAI, donde alias y snapshot pueden diferir). |
| `max_tokens` | **Obligatorio.** Si la respuesta lo supera, se corta y `stop_reason` será `"max_tokens"` en lugar de `"end_turn"`. |
| `temperature` | Rango `0.0`–`1.0` (no llega a `2.0` como OpenAI). Análisis: `0.0`–`0.3`; creativo: `0.7`–`1.0`. |
| `top_p` | Alternativa a `temperature`. |
| `top_k` | **Exclusivo de Anthropic.** Limita la selección a los K tokens más probables antes de aplicar `temperature`/`top_p`. Con `top_k=1`, siempre el más probable. |
| `stop_sequences` | Strings que detienen la generación inmediatamente (el string de parada no se incluye en la respuesta). |
| `thinking` | Razonamiento extendido (Sonnet 4.6, Opus 4.6): `{"type":"enabled","budget_tokens":N}`. Mínimo recomendado 1024 tokens. Con thinking, la respuesta incluye bloques `thinking` además de `text`; esos tokens se facturan como salida. |

## 2.7 Estructura de la respuesta

- `id` (`msg_...`), `type` (siempre `"message"`), `role` (siempre `"assistant"`), `model`.
- `content` — **un array de bloques**, no un string directo. En la mayoría de casos contiene un solo
  bloque de tipo `text`. Con herramientas (`tool_use`) o thinking, puede contener varios bloques de
  tipos diferentes. Por eso conviene iterar:

```python
for block in response.content:
    if block.type == "text":
        print(block.text)
    elif block.type == "tool_use":
        print(f"Tool call: {block.name}({block.input})")
    elif block.type == "thinking":
        print(f"Thinking: {block.thinking}")
```

- `stop_reason` — `"end_turn"` (terminó natural), `"max_tokens"` (se cortó), `"stop_sequence"`
  (generó una secuencia de parada), `"tool_use"` (quiere usar una herramienta).
- `stop_sequence` — cuál se activó (o `None`).
- `usage` — `input_tokens`, `output_tokens`. **No hay `total_tokens`** — lo calculas tú. Con prompt
  caching aparecen `cache_creation_input_tokens` y `cache_read_input_tokens`.

## 2.8 Metadatos, tokens y coste

- `model` devuelve exactamente el mismo string que pasaste (el snapshot está en el ID, sin ambigüedad
  alias/snapshot como en OpenAI).
- **Anthropic no devuelve timestamp** en la respuesta — si lo necesitas, regístralo en tu código.
- Tokens de salida ~5x más caros que los de entrada en la mayoría de modelos de Anthropic.
- `claude-haiku-4-5`: una llamada típica ronda $0.001–$0.002. Algo más caro que `gpt-4o-mini`, pero
  sigue siendo fracciones de centavo.

## 2.9 Manejo de errores y reintentos automáticos

El SDK lanza excepciones tipadas similares a las de OpenAI **y reintenta automáticamente (2 veces por
defecto)** ciertos errores transitorios: conexión, 429 (rate limit), 409 (conflicto) y 5xx.

- `AuthenticationError` (401) — key inválida (empieza por `sk-ant-`).
- `RateLimitError` (429) — límite de requests/tokens por minuto o crédito insuficiente. Los rate
  limits dependen de tu **tier de uso**, que sube automáticamente a medida que acumulas gasto.
- `BadRequestError` (400) — causas comunes en Anthropic: olvidar `max_tokens` (obligatorio), mensajes
  que no alternan `user`/`assistant`, o modelo inexistente.
- `APIConnectionError` — problema de red o caída temporal.
- `InternalServerError` (500/529) — `529` indica API sobrecargada. El SDK reintenta automáticamente.

Configuras los reintentos al crear el cliente: `Anthropic(max_retries=5)` o `max_retries=0` para
desactivarlos. Como el SDK ya gestiona reintentos, normalmente no necesitas tu propio patrón; si
necesitas lógica personalizada (*fallback* a otro proveedor), lo desactivas y lo gestionas tú — algo
que haremos en la Sesión 3.

## 2.10 Diferencias clave a recordar (vs OpenAI)

1. **`max_tokens` es obligatorio** en Anthropic, opcional en OpenAI.
2. **Los mensajes deben alternar** `user` → `assistant` → `user`. OpenAI es más flexible.
3. **No hay helper `output_text`** — siempre `content[0].text`.
4. **No hay timestamp** en la respuesta.
5. **El SDK de Anthropic reintenta automáticamente**; el de OpenAI no.
6. **El rango de `temperature` llega a `1.0`** en Anthropic, a `2.0` en OpenAI.

---

# PARTE 3 — Estructura de una llamada al API de Gemini

## 3.1 El SDK de Google Gen AI

Google da acceso a sus modelos Gemini a través del **Google Gen AI SDK** (`google-genai`), un SDK
unificado que funciona tanto con la **Gemini Developer API** (acceso directo con API key) como con
**Vertex AI** (acceso vía Google Cloud). En el programa usamos la Developer API por su simplicidad:
solo necesitas una API key, sin configuración de proyecto en Google Cloud.

> ⚠️ El SDK anterior (`google-generativeai`) está **deprecado**. Todo el código usa el SDK actual
> `google-genai`, estándar desde 2025.

La interfaz principal es `client.models.generate_content()`.

## 3.2 La llamada completa

```python
from google import genai
from google.genai import types

client = genai.Client()  # Lee GEMINI_API_KEY del entorno

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="What factors should I consider when estimating a database migration?",
    config=types.GenerateContentConfig(
        system_instruction="You are an expert in software project estimation...",
        temperature=0.7,
        max_output_tokens=500,
    ),
)

print(response.text)
```

Diferencias clave respecto a OpenAI y Anthropic: el *system prompt* va dentro de un objeto `config`
(no como parámetro de primer nivel), la entrada va en `contents`, accedes al texto con
**`response.text`**, y **toda la configuración se agrupa en un único objeto `GenerateContentConfig`**.

## 3.3 `system_instruction`: dentro de `config`

El campo `system_instruction` dentro de `config` cumple la función del *system prompt*. Acepta un
**string simple** o una **lista de strings** (cada string se trata como una instrucción independiente,
útil para modularizar):

```python
config=types.GenerateContentConfig(
    system_instruction=[
        "You are a senior software architect.",
        "Your audience is developers with 5+ years of experience.",
        "Always respond in Spanish, maximum 200 words, in prose.",
    ],
)
```

Misma lógica de separación que en los otros proveedores.

## 3.4 `contents`: estructura de mensajes y el rol `model`

Acepta un string simple, una lista mixta o un array de objetos `Content` con roles. Formato completo:

```python
contents=[
    types.Content(role="user", parts=[types.Part(text="What is a REST API?")]),
    types.Content(role="model", parts=[types.Part(text="A REST API is...")]),
    types.Content(role="user", parts=[types.Part(text="What is the difference with GraphQL?")]),
]
```

Roles: `user` y **`model`**. **A diferencia de OpenAI y Anthropic, que usan `assistant`, Gemini usa
`model` como nombre del rol para las respuestas del modelo.** Si usas `assistant`, obtienes un error.

## 3.5 Conversación multi-turno

La API de Gemini es **stateless**. Dos opciones:

- **Opción A — Manual:** reconstruyes el historial con un array de `Content`.
- **Opción B — Helper de chat:** `client.chats.create()` gestiona el historial automáticamente
  (`chat.send_message(...)`, `chat.get_history()`). Es una conveniencia del SDK: internamente sigue
  enviando el historial completo en cada llamada, con el mismo impacto en tokens y coste.

## 3.6 Parámetros (`GenerateContentConfig`)

Toda la configuración va dentro de `GenerateContentConfig` (a diferencia de OpenAI/Anthropic, donde
los parámetros van como argumentos separados):

| Parámetro | Notas |
|---|---|
| `system_instruction` | String o lista de strings. Opcional. |
| `temperature` | Rango `0.0`–`2.0` (igual que OpenAI, más amplio que Anthropic). |
| `max_output_tokens` | **Opcional** en Gemini (a diferencia de Anthropic). Si no se especifica, el modelo decide. |
| `top_p`, `top_k` | `top_k` disponible en Gemini y Anthropic, no en OpenAI. |
| `candidate_count` | Número de respuestas alternativas. Por defecto 1. |
| `stop_sequences` | Secuencias que detienen la generación. |
| `seed` | Para resultados reproducibles (mismo seed + mismo input = misma respuesta). Útil para testing. |
| `safety_settings` | **Filtros de seguridad de contenido**, propios de Gemini. Pueden bloquear respuestas. Ajustables por categoría. Si el modelo rechaza generar, revisa esto. |
| `thinking_config` | `types.ThinkingConfig(thinking_budget=N)`. **Habilitado por defecto** en Gemini 2.5 Flash/Pro y Gemini 3 Pro. Los tokens de pensamiento se facturan como salida; reduce el budget o desactívalo si prima la velocidad. |

## 3.7 Estructura de la respuesta

La respuesta es un objeto `GenerateContentResponse`:

- `response.text` — atajo al texto del primer candidato (equivalente a `output_text` de OpenAI o
  `content[0].text` de Anthropic).
- `candidates` — array, porque `candidate_count` permite generar varias respuestas. Con
  `candidate_count=1` (por defecto), siempre hay un solo candidato.
- `candidates[0].finish_reason` — `STOP` (terminó natural), `MAX_TOKENS` (se cortó), `SAFETY`
  (bloqueado por filtros), `RECITATION` (posible violación de copyright).
- `candidates[0].safety_ratings` — evaluación de seguridad por categoría.
- `model_version` — el snapshot exacto (p. ej. `gemini-2.5-flash-001`).

## 3.8 Metadatos, tokens y coste

- **Gemini no devuelve un ID único de request ni un timestamp** — genera los tuyos para trazabilidad.
- `usage_metadata`:
  - `prompt_token_count` — tokens de entrada (≡ `input_tokens` de OpenAI/Anthropic).
  - `candidates_token_count` — tokens de salida (≡ `output_tokens`).
  - `thoughts_token_count` — tokens de razonamiento (con thinking habilitado). Se facturan como
    salida.
  - `cached_content_token_count` — tokens servidos desde caché (tarifa reducida).
  - `total_token_count` — suma de todos.
- Gemini 2.5 Flash es uno de los modelos más baratos del mercado; para una llamada típica sin
  thinking, el coste es comparable al de `gpt-4o-mini`.

## 3.9 Contar tokens antes de la llamada (exclusivo)

Gemini ofrece un endpoint **gratuito** `client.models.count_tokens()` para estimar el consumo
**antes** de enviar la request. **Ni OpenAI ni Anthropic ofrecen esto como endpoint nativo** — es una
ventaja exclusiva de Gemini para control de costes previo.

## 3.10 Manejo de errores

El SDK lanza excepciones del módulo `google.genai.errors`:

- `401 Unauthorized` — API key no válida o no configurada (`GEMINI_API_KEY` o `GOOGLE_API_KEY`).
- `429 Resource Exhausted` — rate limit. Gemini mide tres dimensiones: **RPM** (requests por minuto),
  **TPM** (tokens por minuto) y **RPD** (requests por día). El free tier es muy restrictivo
  (10–15 RPM); habilitar billing los aumenta drásticamente.
- `400 Bad Request` — modelo inexistente, usar `role="assistant"` en lugar de `role="model"`, o
  `contents` vacío.
- **`SAFETY` block** — no es un error HTTP sino un `finish_reason` en la respuesta. El modelo generó
  contenido pero fue bloqueado por los filtros.
- `500/503 Server Error` — error del lado de Google. Reintenta tras unos segundos.

**A diferencia de Anthropic, el SDK de Gemini NO incluye reintentos automáticos** — debes
implementarlos tú.

## 3.11 Diferencias clave a recordar

1. **El rol del modelo es `"model"`, no `"assistant"`** — usar `"assistant"` produce un error.
2. **Toda la configuración va dentro de `GenerateContentConfig`** — no como argumentos separados.
3. **No hay ID de request ni timestamp** en la respuesta — genera los tuyos.
4. **Los filtros de seguridad pueden bloquear respuestas** sin error HTTP — revisa `finish_reason` y
   `safety_ratings`.
5. **`count_tokens()` es gratuito y exclusivo de Gemini** — úsalo para estimar costes antes de enviar.
6. **El SDK no incluye reintentos automáticos** — implementa tu propia lógica.
7. **Thinking está habilitado por defecto** en Gemini 2.5+ — consume tokens extra facturados como
   salida.

---

# PARTE 4 — Parámetros en modelos de razonamiento

## 4.1 Por qué los modelos de razonamiento son diferentes (para cualquiera)

Un modelo "normal" produce su respuesta de una pasada: lee la pregunta y va escribiendo. Un **modelo
de razonamiento** (OpenAI GPT-5/o3/o4-mini; Anthropic Claude 4/4.5/4.6 con *extended thinking*)
trabaja distinto: internamente **genera varias cadenas de razonamiento, las evalúa, descarta ramas
malas, y solo entonces produce la respuesta final**. Es como un alumno que hace borradores antes de
escribir la versión buena.

Ese proceso lo **calibra el proveedor** para maximizar calidad y seguridad. Si te dejaran tocar
ajustes tradicionales como `temperature` o `top_p`, romperías esa calibración (por ejemplo,
`temperature=0` colapsaría todas las ramas de razonamiento en una sola ruta *greedy*, anulando el
beneficio del enfoque multi-paso). Por eso los proveedores han **bloqueado** varios parámetros de
muestreo y han introducido **parámetros nuevos** (`reasoning_effort`, `verbosity`, `thinking`) para
darte otra vía de control.

## 4.2 OpenAI — modelos afectados

- **Familia o-series:** `o1`, `o1-mini`, `o3`, `o3-mini`, `o3-pro`, `o4-mini`.
- **Familia GPT-5:** `gpt-5`, `gpt-5-mini`, `gpt-5-nano`, `gpt-5.1`, `gpt-5.2`, `gpt-5.3`, `gpt-5.4`
  y variantes.
- **Familia Codex:** `gpt-5-codex`, `gpt-5.2-codex`, `gpt-5.3-codex`.

### Parámetros bloqueados o restringidos

| Parámetro | Estado | Comportamiento |
|---|---|---|
| `temperature` | ❌ No soportado | Fijado en 1. Enviarlo produce error. |
| `top_p` | ❌ No soportado | Fijado en 1. Enviarlo produce error. |
| `presence_penalty` | ❌ No soportado | Fijado en 0. |
| `frequency_penalty` | ❌ No soportado | Fijado en 0. |
| `logprobs` / `top_logprobs` | ❌ No soportado | No exponen probabilidades de tokens. |
| `logit_bias` | ❌ No soportado | No se puede influir en la selección de tokens. |
| `n` | ⚠️ Restringido | Fijado en 1. No se generan múltiples candidatos en paralelo. |
| `max_tokens` | ⚠️ Deprecado | Sustituido por `max_completion_tokens` (Chat Completions) o `max_output_tokens` (Responses). |

### Parámetros nuevos

| Parámetro | Disponible en | Descripción |
|---|---|---|
| `reasoning_effort` / `reasoning.effort` | o1+, GPT-5+ | Controla cuánto "piensa". Valores: `minimal` (GPT-5+), `none` (GPT-5.2+), `low`, `medium` (default), `high`, `xhigh` (GPT-5.2+ y Codex). Más esfuerzo = más tokens de razonamiento = más calidad pero más coste y latencia. |
| `verbosity` | GPT-5+ | Controla la longitud de la respuesta final sin modificar el razonamiento interno (`low`/`medium`/`high`). Reemplaza al control de longitud que antes se hacía con *prompt engineering*. |
| `previous_response_id` | Responses API | Pasa la cadena de pensamiento entre turnos, mejorando calidad y caché. |

### `system` → `developer`

En modelos o-series, los mensajes con `role:"system"` se tratan internamente como `role:"developer"`.
El SDK lo gestiona transparentemente, pero no debes usar ambos roles en la misma request.

## 4.3 Anthropic — modelos con extended thinking

Afectados: Claude Opus 4/4.1/4.5/4.6, Sonnet 4/4.5/4.6, Haiku 4.5. Las restricciones aplican **cuando
se activa `thinking`** en la request. Sin thinking, estos modelos aceptan los parámetros tradicionales
(con las excepciones de abajo).

### Bloqueados/restringidos con thinking activado

| Parámetro | Estado | Comportamiento |
|---|---|---|
| `temperature` | ❌ No modificable | Enviarlo produce error. |
| `top_k` | ❌ No modificable | No puedes ajustarlo. |
| `top_p` | ⚠️ Restringido | Solo valores entre `0.95` y `1.0`. Más bajos fallan. |
| `tool_choice: "any"` o `"tool"` | ❌ No compatible | El *forced tool use* es incompatible con thinking. Usa `"auto"`. |
| Response pre-filling | ❌ No soportado | No puedes pre-rellenar el inicio de la respuesta del assistant. |

### Restricción adicional en modelos 4.5+ (incluso SIN thinking)

Claude Sonnet 4.5 y Haiku 4.5 (y posteriores) introdujeron una regla que aplica **siempre**:
`temperature` + `top_p` son **mutuamente excluyentes**. No puedes enviar ambos en la misma request.
Esta restricción **no existía** en Claude 3.5 (que los aceptaba ambos), así que código que funcionaba
con 3.5 puede romperse al migrar a 4.5/4.6.

### Parámetros nuevos

| Parámetro | Disponible en | Descripción |
|---|---|---|
| `thinking` | Claude 4+ con thinking | `{"type":"enabled","budget_tokens":N}`. El budget es un objetivo, no un límite estricto. Mínimo recomendado: 1024 tokens. |
| `interleaved-thinking-2025-05-14` (beta header) | Claude 4+ | Thinking intercalado con *tool use*: el modelo piensa entre llamadas a herramientas. |
| `context-management-2025-06-27` (beta header) | Sonnet/Haiku/Opus 4+ | Habilita `clear_thinking_20251015` para limpiar automáticamente los thinking blocks de turnos anteriores y reducir consumo de contexto. |

## 4.4 Tabla resumen: ¿qué sigue funcionando y qué no?

| Parámetro | OpenAI clásicos (`gpt-4o`, `gpt-4o-mini`) | OpenAI razonamiento (o-series, GPT-5+) | Anthropic clásicos (`claude-3.5`) | Anthropic 4.5+ sin thinking | Anthropic 4+ con thinking |
|---|---|---|---|---|---|
| `temperature` | ✅ | ❌ | ✅ | ⚠️ (no junto con `top_p`) | ❌ |
| `top_p` | ✅ | ❌ | ✅ | ⚠️ (no junto con `temperature`) | ⚠️ (solo 0.95–1.0) |
| `top_k` | — | — | ✅ | ✅ | ❌ |
| `presence_penalty` | ✅ | ❌ | — | — | — |
| `frequency_penalty` | ✅ | ❌ | — | — | — |
| `logprobs`/`top_logprobs` | ✅ | ❌ | — | — | — |
| `logit_bias` | ✅ | ❌ | — | — | — |
| `n > 1` | ✅ | ❌ | — | — | — |
| `seed` | ✅ | ✅ | ❌ | ❌ | ❌ |
| `stop_sequences`/`stop` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `max_tokens`/`max_output_tokens` | ✅ | ✅ (usar `max_output_tokens`/`max_completion_tokens`) | ✅ (obligatorio) | ✅ (obligatorio) | ✅ (obligatorio) |
| `reasoning_effort` | ❌ | ✅ | — | — | — |
| `verbosity` | ❌ | ✅ (GPT-5+) | — | — | — |
| `thinking` | — | — | ❌ | — | ✅ |
| Forced tool use | ✅ | ✅ | ✅ | ✅ | ❌ |
| Response pre-fill | — | — | ✅ | ✅ | ❌ |

Leyenda: ✅ soportado · ❌ no soportado · ⚠️ con restricciones · — no aplicable.

## 4.5 Implicaciones prácticas para el programa

1. **Si construyes sobre modelos no-razonamiento, sigue todo igual.** Usamos `gpt-4o-mini` y
   `claude-haiku-4-5-20251001`. Haiku 4.5 sí tiene la restricción de no combinar `temperature` y
   `top_p`, pero como en el notebook solo usamos `temperature`, no nos afecta.
2. **Si migras a un modelo de razonamiento, revisa tu código.**
   - **OpenAI (GPT-5, o3, o4-mini):** elimina `temperature`, `top_p`, `frequency_penalty`,
     `presence_penalty`, `logprobs`, `logit_bias`. Sustitúyelos por `reasoning_effort` y `verbosity`.
   - **Anthropic con thinking:** elimina `temperature` y `top_k`. Si necesitas `top_p`, úsalo solo en
     rango `0.95–1.0`. No uses forced tool use ni pre-filling.
3. **El "coste del razonamiento" se factura como tokens de salida.** Tanto `reasoning_tokens`
   (OpenAI) como `thinking_tokens` (Anthropic) se facturan al precio de salida aunque no aparezcan en
   la respuesta visible. Un modelo con `reasoning_effort: "high"` puede consumir 10x más tokens de
   salida que el mismo modelo con `reasoning_effort: "minimal"` para la misma pregunta.
4. **Regla mnemotécnica:** *los modelos de razonamiento te quitan el control del muestreo y te dan
   control sobre el razonamiento.* Pierdes `temperature`, `top_p`, `presence_penalty`…; ganas
   `reasoning_effort` y `verbosity` (OpenAI) o `thinking.budget_tokens` (Anthropic). Es un
   intercambio deliberado: el proveedor se reserva el control fino del muestreo porque lo necesita
   para orquestar el proceso multi-paso, y a cambio te da palancas de más alto nivel.

---

# PARTE 5 — Tokenización: conceptos avanzados

## 5.1 El problema que resuelve la tokenización (para cualquiera)

Los modelos de lenguaje **no leen texto**. Un *transformer* opera exclusivamente sobre secuencias de
números enteros. La **tokenización** es el proceso que convierte texto legible por humanos en una
secuencia de IDs numéricos que el modelo puede procesar, y viceversa.

Cuando envías el string `"How long would a database migration take?"`, lo que llega al modelo es algo
como `[4438, 1317, 1053, 264, 7316, 12507, 1935, 30]`. Cada número es un **token**: una unidad
discreta que el modelo ha aprendido a manejar durante su entrenamiento.

Para un AI Engineer, entender la tokenización no es académico: es entender la **unidad de medida
fundamental de todo tu stack**. Cada decisión de diseño —la longitud de tu system prompt, el idioma
en el que operas, el formato de datos que inyectas como contexto— se traduce en tokens, y **los
tokens se traducen en dinero y en latencia**.

## 5.2 De texto a números: el flujo completo

El proceso tiene tres fases:

- **Fase 1 — Codificación a bytes:** el texto se convierte a su representación en bytes usando UTF-8.
  `A` ocupa 1 byte, `ñ` ocupa 2 bytes, un emoji como 🚀 ocupa 4 bytes. **Los idiomas con caracteres
  no-ASCII (español, chino, árabe) consumen más bytes por carácter.**
- **Fase 2 — Pre-tokenización:** el texto se divide en fragmentos usando reglas (normalmente
  expresiones regulares) que separan por espacios, puntuación y categorías de caracteres. Garantizan
  que ciertos *merges* nunca crucen fronteras de categoría — un número nunca se fusionará con una
  letra.
- **Fase 3 — BPE (Byte Pair Encoding):** dentro de cada fragmento, el algoritmo BPE aplica una tabla
  de *merges* aprendida durante el entrenamiento del tokenizador para combinar bytes en tokens cada
  vez más grandes. El resultado es la secuencia de IDs numéricos.

```
Text:      'PostgreSQL migration'
Token IDs: [5765, 48528, 12507]
  ID  5765 → 'Postgre'
  ID 48528 → 'SQL'
  ID 12507 → ' migration'   # el espacio anterior es parte del token
```

Que `' migration'` incluya el espacio anterior no es un error — es una decisión de diseño del
tokenizador que afecta a cómo el modelo procesa el texto.

## 5.3 BPE: el algoritmo que domina la industria

BPE es el algoritmo usado por GPT-2/3/4/5, Llama, Mistral y la mayoría de LLMs actuales. Propuesto en
1994 como compresión de datos, adaptado al NLP en 2015. El **entrenamiento del tokenizador** (que es
independiente del entrenamiento del modelo) es iterativo:

1. Se parte de un vocabulario base de 256 tokens (uno por cada valor de byte posible).
2. Se escanea un corpus grande y se cuenta la frecuencia de cada par adyacente de tokens.
3. Se fusiona el par más frecuente en un nuevo token y se añade al vocabulario.
4. Se repite hasta alcanzar el tamaño de vocabulario deseado.

El resultado es una **tabla de merges** ordenada: esta tabla **es** el tokenizador.

### Tamaños de vocabulario y otros algoritmos

| Modelo | Encoding | Vocabulario | Año |
|---|---|---|---|
| GPT-2 | `gpt2` | ~50K | 2019 |
| GPT-3.5/4 | `cl100k_base` | ~100K | 2023 |
| GPT-4o | `o200k_base` | ~200K | 2024 |

Un vocabulario más grande = secuencias de tokens más cortas (menos cómputo en el transformer) y mejor
cobertura multilingüe, pero matrices de embedding más grandes. Los vocabularios se han **cuadruplicado
en tres años**.

- **BPE** — el estándar de facto. La variante moderna es *byte-level BPE*, que opera sobre los 256
  valores de byte en lugar de sobre caracteres Unicode, eliminando el problema de los caracteres
  desconocidos.
- **WordPiece** — usado por BERT. Similar a BPE pero el criterio de merge es la maximización de la
  verosimilitud del corpus, no la frecuencia bruta.
- **Unigram** — usado por T5 y ALBERT. Enfoque opuesto: empieza con un vocabulario enorme y va
  eliminando tokens cuya ausencia causa el menor incremento de *loss*. Captura mejor las terminaciones
  morfológicas (`-ing`, `-tion`, `-mente`).

Si trabajas con APIs de OpenAI, Anthropic o modelos open source, **estás usando BPE.**

## 5.4 Patrones que te afectan en producción

- **5.4.1 El español consume más tokens que el inglés.** Típicamente un **20–40% más** para el mismo
  contenido semántico; el japonés y el chino pueden consumir el doble o más. El corpus de
  entrenamiento del tokenizador está dominado por inglés. *Decisión de diseño:* algunos equipos
  escriben sus system prompts en inglés (aunque la respuesta sea en español) para reducir el consumo;
  un prompt de 200 tokens en español frente a 150 en inglés acumula 1.000 tokens extra en una
  conversación de 20 turnos. **Regla:** 1.000 tokens ≈ 750 palabras en inglés ≈ 600 en español.
- **5.4.2 El código es relativamente eficiente en tokens.** Los keywords (`def`, `return`, `SELECT`,
  `FROM`) son muy frecuentes en el corpus y tienen tokens dedicados. Los nombres de variables/funciones
  específicos de tu dominio se fragmentan más. Un archivo de 100 líneas de Python puede consumir solo
  300–500 tokens.
- **5.4.3 Los espacios, saltos de línea e indentación son tokens.** `"Hello"` y `" Hello"` (con
  espacio) son tokens **completamente diferentes** con IDs distintos. Un JSON compacto (sin
  indentación) consume significativamente menos tokens que el mismo JSON con *pretty-print*.
  *Implicación:* inyecta datos estructurados (JSON, YAML) en formato compacto; la indentación añade
  legibilidad para humanos pero no aporta nada al modelo.
- **5.4.4 Los números se tokenizan de forma inconsistente.** `"100"` puede ser un solo token mientras
  que `"101"` se divide en `"10"` + `"1"`. Esto explica por qué los LLMs son malos en aritmética: el
  modelo nunca ve los dígitos individuales alineados para calcular columna por columna; ve `"1234"`
  como una unidad semántica opaca. *Implicación:* **nunca dependas de un LLM para cálculos aritméticos
  precisos.** Los LLMs son herramientas de lenguaje, no calculadoras.
- **5.4.5 Los tokens especiales.** Cada tokenizador incluye tokens que marcan estructura: inicio/fin
  de mensaje, separadores de roles, delimitadores de herramientas (`<|endoftext|>`, `<|im_start|>`,
  `<|im_end|>`). Son invisibles para ti (el SDK los gestiona) pero **consumen tokens** y forman parte
  del conteo en `usage.input_tokens`. Por eso el número que reporta la API siempre es ligeramente
  mayor que el que obtienes al tokenizar solo tu texto.

## 5.5 Tokenización y ventanas de contexto

La **ventana de contexto** es el número máximo de tokens que un modelo puede procesar en una sola
llamada. Este límite incluye **todo**: system prompt + historial de mensajes + entrada del usuario +
**respuesta del modelo**. No es solo tu input — la respuesta también cuenta dentro de la ventana.

| Modelo | Ventana | ≈ Páginas |
|---|---|---|
| `gpt-4o-mini` | 128.000 | ~190 |
| `gpt-5.4` | 200.000 | ~300 |
| `claude-haiku-4-5` | 200.000 | ~300 |
| `claude-sonnet-4-6` | 200.000 | ~300 |
| `gemini-2.5-flash` | ~1.000.000 | ~1.500 |
| `gemini-3-pro` | ~2.000.000 | ~3.100 |

(≈ 1 página ≈ 500 palabras ≈ 670 tokens.)

**Cómo se llena la ventana en una conversación:** cada turno acumula todos los tokens anteriores. El
system prompt **se reenvía con cada llamada**. En el turno 9 estás pagando el system prompt por novena
vez, más todo el historial. *Implicación:* una conversación de 20 turnos con un system prompt de 500
tokens acumula 10.000 tokens de entrada extra — coste puro sin valor añadido. Estrategias de
mitigación:

- **Prompt caching** (Anthropic 90% de descuento en cache hits, OpenAI también lo soporta).
- **Truncado de historial** (mantener solo los últimos N turnos).
- **Resumen de turnos anteriores** (comprimir el historial).
- **`previous_response_id`** (OpenAI gestiona el contexto y optimiza caché).

**Contar tokens antes de enviar:** Gemini ofrece `count_tokens()` gratuito; para OpenAI puedes usar
`tiktoken` localmente. La estimación local es aproximada (la API añade tokens especiales de formato
que no se replican exactamente), pero suficiente para estimar coste y verificar que no excedes la
ventana antes de enviar.

## 5.6 Tokenización y coste: las matemáticas que importan

- **5.6.1 La asimetría input/output.** En todos los proveedores, los tokens de salida son **más caros
  que los de entrada** (ratio entre 3x y 10x). Porque cada token de salida requiere una pasada
  completa del modelo, mientras que los de entrada se procesan en paralelo. *Implicación:* optimizar
  la longitud de las respuestas tiene **más impacto en tu factura** que optimizar el prompt. Un system
  prompt que dice `"Maximum 200 words"` o `"Respond in exactly 3 sentences"` no es solo UX — es una
  palanca de coste directa.
- **5.6.2 Proyección de coste a escala.** En un producto SaaS con un asistente IA, la diferencia entre
  `gpt-4o-mini` y `gpt-5.4` para el mismo volumen puede ser de **10–30x en coste mensual**. En muchos
  casos, la calidad del modelo más barato es suficiente, y el ahorro financia otras mejoras. **La
  elección de modelo es una decisión de negocio.**
- **5.6.3 Prompt caching: la optimización más impactante.** Si una porción del input (típicamente el
  system prompt y el contexto inyectado) se repite entre llamadas, los tokens repetidos se sirven
  desde caché con un descuento significativo. Especialmente relevante en arquitecturas CAG y RAG,
  donde el system prompt y el contexto base se repiten en cada llamada. Lo profundizamos en la
  Sesión 3.

## 5.7 Limitaciones fundamentales de la tokenización

- **6.1 El modelo no ve letras.** Pedirle que cuente letras o deletree al revés contradice su
  representación interna. La palabra `"Strawberry"` puede ser un único token (ID 92850); el modelo ve
  el token 92850, no las letras S-t-r-a-w-b-e-r-r-y.
- **6.2 La tokenización no es uniforme entre proveedores.** Cada proveedor entrena su propio
  tokenizador con su propio corpus y vocabulario; el mismo texto produce secuencias de tokens (y
  longitudes) diferentes. **No puedes usar `tiktoken` para estimar exactamente los tokens de Anthropic
  o Gemini.** Anthropic típicamente produce un 5–15% más de tokens que OpenAI para texto en inglés.
  Para Gemini, usa `count_tokens()`.
- **6.3 Tokens "glitch".** En 2023 se descubrió que ciertos tokens producían comportamientos erráticos
  en GPT-3.5/4. El caso famoso fue `"SolidGoldMagikarp"` — un username de Reddit que aparecía con
  suficiente frecuencia en el corpus del tokenizador como para obtener su propio token, pero tan raro
  en el corpus del modelo que su embedding quedó esencialmente aleatorio. **Causa raíz: los datos de
  entrenamiento del tokenizador y los del modelo no son los mismos.** Los tokenizadores modernos
  (`o200k_base`) han eliminado la mayoría, pero el problema persiste como limitación arquitectural.

## 5.8 Resumen: lo que un AI Engineer necesita saber sobre tokens

1. **Los tokens no son palabras.** Son fragmentos de longitud variable producidos por BPE. Una palabra
   puede ser 1 token o 5.
2. **El idioma importa.** El español consume 20–40% más de tokens que el inglés. Afecta directamente a
   tu factura.
3. **Los tokens de salida son 3–6x más caros que los de entrada.** Controlar la longitud de las
   respuestas tiene más impacto en coste que optimizar el prompt.
4. **Cada turno reenvía todo el historial.** El coste crece cuadráticamente, no linealmente. Gestionar
   el contexto no es una optimización — es un requisito de viabilidad económica.
5. **Los tokenizadores varían entre proveedores.** `tiktoken` es solo una aproximación para Anthropic
   y Gemini.
6. **El formato de tus datos consume tokens.** JSON con pretty-print, indentación y saltos de línea
   extra consumen tokens sin aportar valor.
7. **Los modelos no ven letras ni dígitos individuales.** No delegues aritmética ni manipulación de
   strings a un LLM — hazlo en tu código.

---

# PARTE 6 — Comparación de modelos 2026

> ⚠️ Los precios y modelos en el mercado de LLMs cambian con frecuencia. Este apartado refleja el
> estado del mercado a **1 de abril de 2026**. Consulta siempre las páginas oficiales de precios antes
> de tomar decisiones que afecten a producción.

## 6.1 Panorama de proveedores

El mercado de LLMs comerciales está dominado por **cinco proveedores principales**, más un ecosistema
creciente de modelos open source y agregadores.

### Los cinco grandes

- **OpenAI** — líder en amplitud de catálogo. Su familia GPT-5.4 (marzo 2026) cubre desde modelos
  ultra-baratos (Nano) hasta premium con razonamiento avanzado (Pro). Pionero en *computer use* y
  herramientas integradas. El mayor ecosistema de desarrolladores y documentación.
- **Anthropic** — posicionado en calidad y seguridad. Su familia Claude (Haiku 4.5, Sonnet 4.6,
  Opus 4.6) ofrece tres tiers claros. Opus 4.6 lidera benchmarks de ingeniería de software
  (SWE-Bench Verified). Ventana de hasta 1M de tokens en Opus y Sonnet. Fuerte en prompt caching.
- **Google** — ventaja en integración con su ecosistema (Workspace, Cloud, Vertex AI). Familia Gemini
  desde Flash (ultra-barato) hasta Pro (premium). Soporte multimodal nativo fuerte (texto, imagen,
  audio, vídeo). Precios agresivos en los tiers de entrada.
- **xAI (Grok)** — Grok 4 compite en el segmento premium; Grok 4.1 Fast ofrece la **ventana de
  contexto más grande del mercado (2M tokens)**. Acceso a datos en tiempo real de X. Nicho fuerte en
  razonamiento científico.
- **DeepSeek** — el disruptor chino de precios. DeepSeek V3.2 ofrece calidad comparable a modelos que
  cuestan 50–100x más, a precios extremadamente bajos ($0.14–$0.28/MTok). Open source disponible.
  *Contrapartida:* los datos pasan por servidores en China — problema de compliance para ciertos casos.

### Otros proveedores relevantes

- **Mistral** (Francia) — open source con licencia Apache 2.0. Small y Medium con excelente relación
  calidad/precio para deployments donde el control total de los datos es requisito. Relevante para
  GDPR.
- **Meta (Llama)** — open source de referencia. Llama 4 Scout y Maverick disponibles gratuitamente;
  requieren infraestructura propia o acceso vía Together AI, Fireworks o Amazon Bedrock.
- **Cohere** — especializado en RAG empresarial y búsqueda semántica. Command R+ con soporte nativo
  para *retrieval*. Fuerte en multilingüe.

## 6.2 Modelos principales por proveedor (precio por 1M tokens)

**OpenAI:**

| Modelo | Input | Output | Contexto | Caso de uso |
|---|---|---|---|---|
| GPT-5.4 | $2.50 | $15.00 | 1M | Flagship. Coding, computer use, razonamiento. |
| GPT-5.4 Pro | $30.00 | $180.00 | 1M | Razonamiento extendido para problemas muy complejos. Premium. |
| GPT-5.4 mini | $0.75 | $4.50 | 400K | Rápido y capaz. Coding, agentes, multimodal. |
| GPT-5.4 nano | $0.20 | $1.25 | 400K | Ultra-barato. Clasificación, extracción, subagentes. Solo API. |
| GPT-5.2 | $1.75 | $14.00 | 400K | Generación anterior. Se retira en junio 2026. |
| GPT-5 mini | $0.25 | $2.00 | 400K | Buen balance coste/calidad para tareas sencillas. |
| GPT-5 nano | $0.05 | $0.40 | 400K | El más barato de OpenAI con calidad aceptable. |
| GPT-4o-mini | $0.15 | $0.60 | 128K | Legacy. Muy barato pero superado por GPT-5 nano. |

*Nota:* precios se duplican para requests > 272K tokens en GPT-5.4/Pro. Batch API 50% off. Cached
inputs hasta 90% off. **API: Responses (recomendada) + Chat Completions (indefinida).**

**Anthropic (Claude):**

| Modelo | Input | Output | Contexto | Caso de uso |
|---|---|---|---|---|
| Claude Opus 4.6 | $5.00 | $25.00 | 1M | Líder en ingeniería de software. Razonamiento complejo. Premium. |
| Claude Sonnet 4.6 | $3.00 | $15.00 | 1M | Muy buen equilibrio calidad/precio. Extended thinking. |
| Claude Sonnet 4.5 | $3.00 | $15.00 | 1M | Generación anterior de Sonnet. |
| Claude Haiku 4.5 | $1.00 | $5.00 | 200K | Rápido y económico. Volumen alto y complejidad media. |

*Nota:* prompt caching 90% off en cache reads (solo 10% del precio base); cache writes 1.25x base.
Batch API 50% off. **API: Messages (única interfaz).**

**Google (Gemini):**

| Modelo | Input | Output | Contexto | Caso de uso |
|---|---|---|---|---|
| Gemini 3 Pro | $2.00 | $12.00 | 66K | Última generación. Multimodal fuerte (incluye generación de imágenes). |
| Gemini 3 Flash | $0.50 | $3.00 | 1M | Rápido y barato. Excelente para volumen. |
| Gemini 2.5 Pro | $2.50 | $15.00 | 1M | Generación anterior. Fuerte en razonamiento y multimodal. |
| Gemini 2.5 Flash | $0.15 | $0.60 | 1M | Ultra-barato con 1M de contexto. Ideal para procesamiento masivo. |

*Nota:* context caching 90% off en cache reads. Integración nativa con Google Cloud/Workspace/AI
Studio. **API: Gemini API (compatible con formato OpenAI vía adaptadores).**

**xAI (Grok):** Grok 4 ($3/$15, 256K) · Grok 4.1 Fast ($0.20/$0.50, **2M** — el contexto más grande
del mercado). API compatible con formato OpenAI.

**DeepSeek:** V3.2 ($0.14/$0.28, 164K — disruptor de precios) · R1 ($0.55/$2.19, 128K — razonamiento,
competidor de o3/o4-mini a coste mínimo). Open source self-hosting; datos en China.

**Mistral:** Large ($2/$6, 128K) · Small 4 ($0.10/$0.30, 128K, Apache 2.0) · Medium ($0.40/$1.10,
64K). Open source permisivo, ideal self-hosting con control total de datos (GDPR).

**Meta (Llama):** Maverick ($0.15/$0.60, 1M) · Scout ($0.08/$0.30, 1M) · Llama 3.3 70B (gratuito* vía
OpenRouter, 128K). Precios vía hosting; self-hosting gratuito pero requiere infra GPU.

## 6.3 ¿Qué modelo elegir? (comparativa por caso de uso)

| Caso de uso | Recomendación principal | Alternativa económica |
|---|---|---|
| Chatbot / asistente conversacional | Claude Sonnet 4.6 o GPT-5.4 | Claude Haiku 4.5 o GPT-5.4 mini |
| Generación de código | Claude Opus 4.6 o GPT-5.4 | GPT-5.4 mini o DeepSeek V3.2 |
| Análisis de documentos largos | Gemini 2.5 Flash (1M) o Claude Sonnet 4.6 | Grok 4.1 Fast (2M) |
| Clasificación / extracción de datos | GPT-5.4 nano o GPT-5 nano | DeepSeek V3.2 o Mistral Small 4 |
| Razonamiento complejo | Claude Opus 4.6 o GPT-5.4 Pro | DeepSeek R1 |
| Procesamiento masivo (batch) | DeepSeek V3.2 o Gemini 2.5 Flash | GPT-5 nano con Batch API |
| Prototipado rápido | GPT-5.4 nano o Gemini 2.5 Flash | Llama 3.3 70B (gratuito) |
| Compliance GDPR estricto | Mistral (self-hosted) o Llama (self-hosted) | Anthropic (datos en US/EU) |

## 6.4 Conceptos clave de pricing

- **Tokens: la unidad de medida.** Se factura por tokens, no por palabras ni caracteres. Un token ≈ 4
  caracteres en inglés, o ~0.75 palabras. En español, peor (más tokens por palabra) por las tildes, la
  ñ y palabras más largas. *Regla:* 1.000 tokens ≈ 750 palabras en inglés ≈ 600 en español.
- **Asimetría input/output.** Salida 3x–10x más cara que entrada (cada token de salida requiere una
  pasada completa; los de entrada se procesan en paralelo). Optimizar la longitud de las respuestas
  pesa más en coste que optimizar los prompts.
- **Prompt caching.** Reutiliza los cálculos internos de tokens repetidos:

  | Proveedor | Cache read (descuento) | Cache write (sobrecoste) |
  |---|---|---|
  | OpenAI | 50–90% | Sin sobrecoste (automático) |
  | Anthropic | 90% | 25% sobrecoste |
  | Google | 90% | Sin sobrecoste |

  Especialmente relevante en arquitecturas CAG y RAG donde el system prompt y el contexto base se
  repiten en cada llamada.
- **Batch API.** Todos los grandes ofrecen procesamiento asíncrono (normalmente < 24h) con **50% de
  descuento**. Ideal para procesamiento masivo que no requiere respuesta en tiempo real: análisis de
  documentos, generación de contenido, clasificación.

## 6.5 Agregadores y routers

Para proyectos que usen múltiples proveedores (como haremos en el programa):

- **OpenRouter** — plataforma SaaS que da acceso a 500+ modelos de todos los proveedores a través de
  una sola API y un solo billing. Cobra un **5.5% sobre los precios base**. No requiere cuentas
  separadas. Ideal para prototipado. Incluye modelos gratuitos (Llama 3.3, Gemma 3, DeepSeek R1).
- **LiteLLM** — librería open source que unifica la interfaz de 100+ proveedores en un formato
  compatible con OpenAI. **Self-hosted, sin markup de precio.** Soporta load balancing, fallback
  automático y tracking de costes por equipo. Más control pero más setup. Ideal para producción.

Ambas las exploramos en el programa al construir la **capa de abstracción de proveedores**.

## 6.6 Tendencias del mercado

- **Los precios caen rápidamente.** ~80% de bajada entre principios de 2025 y principios de 2026. Lo
  que hoy cuesta $0.15/MTok costaba $0.60/MTok hace un año.
- **Multi-modelo es el estándar.** Un modelo barato para tareas simples (clasificación, routing), uno
  mid-tier para la mayoría del trabajo, y uno premium para casos difíciles. Reduce costes entre un
  60% y un 80% frente a usar siempre el premium.
- **El contexto crece.** De 4K tokens (GPT-3.5, 2023) a 1–2M (GPT-5.4, Gemini, Grok 4.1 Fast, 2026).
  Habilita arquitecturas CAG más potentes y reduce la necesidad de *chunking* agresivo en RAG.
- **Open source cierra la brecha.** Llama 4, DeepSeek V3.2 y Qwen 3 compiten en calidad con modelos
  comerciales que cuestan 10–50x más. Para empresas con capacidad de infraestructura GPU, el
  self-hosting es cada vez más viable.

---

## Cómo conecta con nuestro ejercicio y con el directo

Esta sesión es la **base conceptual de todo el stack**. Las decisiones que tomamos en el estimador se
apoyan directamente en esta teoría:

- **Por qué separamos `instructions`/`system` del `input`/`messages`:** es la base de la arquitectura
  **CAG** — el desarrollador controla el comportamiento (prompt fijo), el usuario solo aporta su
  pregunta. El usuario nunca ve ni modifica las instrucciones del sistema.
- **Por qué usamos `gpt-4o-mini` y `claude-haiku-4-5` en los ejercicios:** relación calidad/precio.
  No son modelos de razonamiento, así que todos los parámetros tradicionales (`temperature`,
  `max_tokens`…) funcionan sin restricciones.
- **Por qué la telemetría de tokens importa:** porque tokens = dinero, la salida es más cara que la
  entrada, y el coste de una conversación crece con cada turno. Medir tokens no es opcional.
- **Por qué la capa de abstracción de proveedores (Sesión 3) tiene sentido:** las tres APIs hacen lo
  mismo con envoltorios distintos (rol `assistant` vs `model`, `output_text` vs `content[0].text`,
  `max_tokens` opcional vs obligatorio, reintentos automáticos o no). Unificarlas detrás de una
  interfaz común —o usar LiteLLM— nos permite cambiar de proveedor sin reescribir el producto.

### Chuleta de una página (lo imprescindible)

- **Estructura universal:** toda llamada = **instrucciones + entrada + configuración → texto +
  metadatos**. Lo que cambia entre proveedores es el envoltorio.
- **OpenAI (Responses):** `instructions` + `input` + `output_text`. Stateless con opción
  `previous_response_id`. Dos APIs (Responses recomendada, Chat Completions el patrón común).
- **Anthropic (Messages):** `system` + `messages` (alternan `user`↔`assistant`) + `content[0].text`.
  **`max_tokens` obligatorio.** Sin timestamp. SDK reintenta solo. `temperature` máx `1.0`.
- **Gemini (`generate_content`):** todo en `GenerateContentConfig`; rol **`model`** (no `assistant`);
  `response.text`. `count_tokens()` gratis. Sin ID/timestamp. Filtros de seguridad pueden bloquear.
  SDK **no** reintenta. Thinking on por defecto en 2.5+.
- **Modelos de razonamiento:** te **quitan** muestreo (`temperature`, `top_p`, penalties…) y te
  **dan** razonamiento (`reasoning_effort`/`verbosity` en OpenAI, `thinking.budget_tokens` en
  Anthropic). El razonamiento se factura como **output**.
- **Tokenización:** tokens ≠ palabras (BPE). Español 20–40% más caro que inglés. Output 3–10x más caro
  que input. Cada turno reenvía todo el historial (coste cuadrático). JSON compacto > pretty-print. El
  modelo no ve letras ni dígitos → no le delegues aritmética. Tokenizadores distintos por proveedor
  (`tiktoken` solo aproxima OpenAI).
- **Mercado 2026:** 5 grandes (OpenAI, Anthropic, Google, xAI, DeepSeek) + open source (Mistral,
  Llama) + agregadores (OpenRouter, LiteLLM). Multi-modelo = estándar (−60/80% coste). Prompt caching
  hasta 90% off. Batch API 50% off. Contexto hasta 1–2M. **La elección de modelo es una decisión de
  negocio.**
