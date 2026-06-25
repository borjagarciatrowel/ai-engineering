# Sesión 01 — APIs de LLMs, parámetros y tokenización (versión clara)

> Versión simplificada del resumen de los 6 artículos de la Sesión 1.
> Misma información, menos paja. Cada término técnico se explica en una frase.
> **Hilo conductor:** una llamada a un LLM es siempre la misma idea —**instrucciones + entrada + configuración → respuesta + metadatos**—; lo que cambia entre proveedores es el envoltorio, no el concepto.

---

## Glosario base (léelo una vez y vuelve cuando haga falta)

| Término | Qué es, en una frase |
|---|---|
| **LLM** | Modelo de lenguaje: un programa que recibe texto y devuelve texto prediciendo qué fragmento viene a continuación. |
| **API** | La puerta para usar el modelo desde tu código: envías una petición por internet y recibes la respuesta. |
| **SDK** | La librería oficial del proveedor que envuelve esas llamadas HTTP (`openai`, `anthropic`, `google-genai`). |
| **System prompt** | Las instrucciones del desarrollador que fijan el "carácter" del asistente; el usuario final no las ve. |
| **Token** | La unidad mínima en la que el modelo trocea el texto (ni letra ni palabra, algo intermedio). **Todo se factura por tokens → los tokens son dinero.** |
| **Stateless (sin memoria)** | El modelo **no recuerda** la conversación; para que "recuerde", reenvías todo el historial en cada llamada. |
| **Modelo de razonamiento** | Generación nueva que "piensa" antes de responder; ganas calidad pero pierdes control sobre algunos ajustes, y ese pensamiento se factura. |
| **Ventana de contexto** | El máximo de tokens que cabe en una llamada, contando entrada **y** respuesta. |
| **Temperature** | El mando de aleatoriedad: `0.0` = siempre lo más probable (determinista); alto = más creativo. |

---

## La idea en una página

Un **LLM** recibe texto y devuelve texto: no "entiende", predice qué viene después una y otra vez. Para usarlo llamas a un **API** del proveedor (OpenAI, Anthropic, Google…).

Toda llamada tiene **tres ingredientes de entrada**:
1. **Instrucciones del sistema** ("eres experto en estimación, responde en español, sé conciso"). Las pone el desarrollador; el usuario no las ve.
2. **Entrada del usuario** (la pregunta concreta). Lo único que cambia en cada interacción.
3. **Configuración** (qué modelo, cuánta creatividad, cuánto puede extenderse la respuesta…).

Y devuelve **dos cosas**: el **texto de respuesta** y unos **metadatos** (tokens gastados, modelo exacto, si terminó bien o se cortó…).

> El resto del documento es esta misma idea contada con precisión para los tres grandes proveedores, más dos capítulos transversales: **tokenización** y **comparación de modelos**.

---

# Parte 1 — El API de OpenAI

## Dos APIs, una recomendación

> **Responses API** (`client.responses.create`) = la API moderna de OpenAI (marzo 2025); unifica las anteriores en una interfaz más limpia, con herramientas integradas, estado entre turnos y mejor rendimiento con razonamiento. **Es la recomendada para todo proyecto nuevo.**
> **Chat Completions API** (`client.chat.completions.create`) = la anterior; soportada indefinidamente pero ya no recomendada. Su estructura de `messages` con roles (`system`/`user`/`assistant`) **es el patrón que comparten casi todos los demás proveedores**, así que conviene entenderla.

> **En el programa usamos la Responses API.** Chat Completions aparecerá con otros proveedores o agregadores (LiteLLM).

## La llamada completa

```python
from openai import OpenAI
client = OpenAI()  # Lee OPENAI_API_KEY del entorno

response = client.responses.create(
    model="gpt-4o-mini",
    instructions="You are a software project estimation expert...",
    input="What factors should I consider when estimating a database migration?",
    temperature=0.7,
    max_output_tokens=500,
)
print(response.output_text)
```

Diferencias clave vs Chat Completions: las instrucciones van en un parámetro **dedicado** (`instructions`, no como un mensaje más), la entrada va en `input`, y el texto se lee con **`response.output_text`** (no `choices[0].message.content`).

## `instructions`: rol, instrucciones y restricciones

Cumple la función del *system prompt*. Tres componentes:
- **Rol** — quién es el modelo ("senior estimation consultant"). Fija conocimiento y marco.
- **Instrucciones operativas** — qué debe hacer ("responde en español", "incluye un rango").
- **Restricciones** — qué **NO** debe hacer ("no inventes datos", "pregunta antes de adivinar"). Tan importantes como las instrucciones.

> **Por qué importa la separación:** el desarrollador define `instructions` (fijo) y el usuario aporta `input` (variable). Esa separación es la base de la arquitectura **CAG** que construimos en el programa: el usuario no sabe que hay un prompt detrás.

> **CAG** = Context-Augmented Generation; la arquitectura donde el desarrollador inyecta contexto fijo y el usuario solo aporta su pregunta.

## `input`: estructura de mensajes

- **String simple** — un solo turno: `input="What is a REST API?"`.
- **Array de mensajes con roles** — multi-turno o más control:
  - `user` — mensajes del humano.
  - `assistant` — respuestas previas del modelo (dan contexto).
  - `developer` — instrucciones del desarrollador intercaladas (equivale al antiguo `system`). Las `instructions` de primer nivel **tienen prioridad** sobre estas.

## Conversación multi-turno

El modelo **no mantiene estado**. Dos opciones:
- **A — Manual:** incluyes todo el historial en `input` en cada llamada.
- **B — `previous_response_id`** (exclusivo de Responses): pasas el ID de la respuesta anterior y OpenAI recupera el contexto. Requiere `store=True`. Simplifica el código y mejora caché (menos tokens repetidos = menos coste). **Contrapartida:** estás guardando datos en servidores de OpenAI; con privacidad estricta, la opción manual puede ser preferible.

## Parámetros de configuración

| Parámetro | Para qué sirve |
|---|---|
| `model` | Qué modelo. En el programa, `gpt-4o-mini` por calidad/precio. |
| `temperature` | Aleatoriedad. Análisis/estimación: `0.0`–`0.3`; creativo: `0.7`–`1.0`. |
| `max_output_tokens` | Techo de tokens de salida. Si la respuesta lo supera, se corta y `status` = `"incomplete"`. **Es el límite, no lo que usará.** |
| `store` | Si OpenAI guarda la respuesta. Necesario para `previous_response_id`. Por defecto `True`; `False` con datos sensibles. |
| `top_p` | Alternativa a `temperature` (núcleo de probabilidad). **Usa uno u otro, nunca ambos.** |
| `reasoning` | Solo modelos de razonamiento (`o3`, `o4-mini`…). Cuánto "piensa". |
| `tools` | Herramientas nativas: `web_search_preview`, `file_search`, `code_interpreter`, `computer_use`. Ventaja sobre Chat Completions. |

## Estructura de la respuesta

- `output_text` — atajo al texto generado.
- `output` — array de Items tipados (mensajes, tool calls…); se itera cuando hay herramientas.
- `status` — `"completed"` / `"incomplete"` (mira `incomplete_details`) / `"failed"` (mira `error`).
- `id` (`resp_...`) — doble uso: trazabilidad y encadenar turnos con `previous_response_id`.
- `model` — el **snapshot exacto** usado, no el alias. Pides `"gpt-4o-mini"` y recibes `"gpt-4o-mini-2024-07-18"`. OpenAI actualiza modelos periódicamente.
- `created_at` — timestamp Unix.
- `usage` — `input_tokens`, `output_tokens`, `total_tokens`, `output_tokens_details.reasoning_tokens`.

## Tokens y coste

- **Tokens de entrada** — todo lo que envías (`instructions` + historial + última entrada). Crece turno a turno.
- **Tokens de salida** — lo que genera el modelo. Más caros (2x–5x según modelo).
- **Tokens de razonamiento** — en modelos de razonamiento, el "pensamiento" interno. **Se facturan como salida** aunque no se vean.

```python
# gpt-4o-mini: precio por 1M de tokens
INPUT_PRICE, OUTPUT_PRICE = 0.15, 0.60
input_cost = (response.usage.input_tokens / 1_000_000) * INPUT_PRICE
output_cost = (response.usage.output_tokens / 1_000_000) * OUTPUT_PRICE
```

Una llamada típica con `gpt-4o-mini` ronda **$0.0001–$0.0005** (fracciones de centavo). Despreciable por llamada, pero a escala es un factor de diseño. La Responses API tiene **mejor caché** que Chat Completions (40%–80% de mejora según OpenAI).

## Manejo de errores

El SDK lanza excepciones tipadas:
- `AuthenticationError` (401) — key inválida, expirada o ausente. El error más común al empezar.
- `RateLimitError` (429) — superado el límite por minuto **o** crédito insuficiente. Esperar y reintentar, o añadir crédito.
- `BadRequestError` (400) — modelo incorrecto, mensajes mal formados, parámetro fuera de rango. El mensaje suele ser descriptivo.
- `APIConnectionError` — no se puede conectar (red, firewall, caída).
- `InternalServerError` (500) — error de OpenAI. Reintenta tras unos segundos.

Para errores transitorios, el patrón estándar es **reintento con espera exponencial** (1s, 2s, 4s…). En la Sesión 3 lo evolucionamos con estrategias de *fallback*.

## Equivalencia Responses ↔ Chat Completions

| Concepto | Responses API | Chat Completions API |
|---|---|---|
| Instrucciones | `instructions="..."` | `messages=[{"role":"system",...}]` |
| Entrada | `input="..."` o `input=[...]` | `messages=[{"role":"user",...}]` |
| Texto de respuesta | `response.output_text` | `response.choices[0].message.content` |
| Límite de tokens | `max_output_tokens` | `max_tokens` |
| Tokens entrada / salida | `usage.input_tokens` / `output_tokens` | `usage.prompt_tokens` / `completion_tokens` |
| Estado | `response.status` | `choices[0].finish_reason` |
| Encadenar | `previous_response_id` | Reconstruir array a mano |
| Herramientas integradas | `tools=[{"type":"web_search_preview"}]` | No nativo |
| Almacenamiento | `store=True/False` | No aplica (siempre stateless) |

---

# Parte 2 — El API de Anthropic

## Una sola API: Messages

> **Messages API** (`client.messages.create`) = la única API de Anthropic; toda la funcionalidad vive aquí. Patrón similar a Chat Completions (array de mensajes con roles) pero con tres diferencias: el *system prompt* va en parámetro separado, la respuesta tiene otra estructura, y **`max_tokens` es obligatorio**.

## La llamada completa

```python
from anthropic import Anthropic
client = Anthropic()  # Lee ANTHROPIC_API_KEY del entorno

response = client.messages.create(
    model="claude-haiku-4-5-20251001",
    system="You are a software project estimation expert...",
    messages=[{"role": "user", "content": "What factors should I consider..."}],
    max_tokens=500,
    temperature=0.7,
)
print(response.content[0].text)
```

Diferencias vs OpenAI: el *system prompt* va en `system` (no dentro de `messages`), `max_tokens` es **obligatorio**, y el texto se lee con **`content[0].text`**.

## `system`: el system prompt como parámetro separado

Igual que `instructions` de OpenAI. Acepta **string** o **array de bloques** (el array sirve para combinar texto con `cache_control` → *prompt caching*). Para los ejercicios, el string basta.

## `messages`: la regla de alternancia

Cada mensaje tiene `role` (`user` o `assistant`) y `content`. **Anthropic NO tiene rol `system` dentro del array** — las instrucciones van siempre en `system`.

> **Regla de alternancia:** los mensajes deben **alternar estrictamente** `user` → `assistant` → `user`. El primero debe ser de `user`. No puedes poner dos del mismo rol seguidos.

```python
# ❌ dos user consecutivos
messages=[{"role":"user","content":"Hello"}, {"role":"user","content":"How are you?"}]
# ✅ alterna user → assistant → user
messages=[
    {"role":"user","content":"Hello"},
    {"role":"assistant","content":"Hi! How can I help you?"},
    {"role":"user","content":"How are you?"},
]
```

Si necesitas varias piezas del usuario en un turno, combínalas en un mensaje o usa *content blocks*.

## Conversación multi-turno

**Stateless.** **No hay equivalente a `previous_response_id`** — el historial es siempre manual. Control total, pero gestionas el array tú. Cada turno reenvía **todo el historial** como tokens de entrada → el coste crece. Anthropic lo mitiga con **prompt caching** (hasta 90% de descuento en *cache hits*).

## Parámetros de configuración

| Parámetro | Notas |
|---|---|
| `model` | `claude-haiku-4-5-20251001` en el programa. Los IDs **incluyen la fecha del snapshot** (sin ambigüedad alias/snapshot como OpenAI). |
| `max_tokens` | **Obligatorio.** Si se supera, `stop_reason` = `"max_tokens"` en lugar de `"end_turn"`. |
| `temperature` | Rango `0.0`–`1.0` (no llega a `2.0` como OpenAI). |
| `top_p` | Alternativa a `temperature`. |
| `top_k` | **Exclusivo de Anthropic.** Limita a los K tokens más probables antes de `temperature`/`top_p`. |
| `stop_sequences` | Strings que detienen la generación (el string de parada no se incluye). |
| `thinking` | Razonamiento extendido (Sonnet 4.6, Opus 4.6): `{"type":"enabled","budget_tokens":N}`. Mínimo recomendado 1024. Los bloques `thinking` se facturan como salida. |

## Estructura de la respuesta

- `id` (`msg_...`), `type` (`"message"`), `role` (`"assistant"`), `model`.
- `content` — **un array de bloques**, no un string. Normalmente un bloque `text`; con herramientas (`tool_use`) o thinking, varios. Por eso conviene iterar:

```python
for block in response.content:
    if block.type == "text":      print(block.text)
    elif block.type == "tool_use": print(f"Tool: {block.name}({block.input})")
    elif block.type == "thinking": print(f"Thinking: {block.thinking}")
```

- `stop_reason` — `"end_turn"` (natural), `"max_tokens"` (cortado), `"stop_sequence"`, `"tool_use"`.
- `stop_sequence` — cuál se activó (o `None`).
- `usage` — `input_tokens`, `output_tokens`. **No hay `total_tokens`** — lo calculas tú. Con caché aparecen `cache_creation_input_tokens` y `cache_read_input_tokens`.

## Metadatos, tokens y coste

- `model` devuelve exactamente el string que pasaste (el snapshot está en el ID).
- **Anthropic no devuelve timestamp** — regístralo tú si lo necesitas.
- Salida ~5x más cara que entrada en la mayoría de modelos.
- `claude-haiku-4-5`: llamada típica ~**$0.001–$0.002**. Algo más caro que `gpt-4o-mini`, pero sigue siendo fracciones de centavo.

## Manejo de errores y reintentos automáticos

El SDK lanza excepciones tipadas **y reintenta automáticamente (2 veces por defecto)** ciertos transitorios: conexión, 429, 409 y 5xx.
- `AuthenticationError` (401) — key inválida (empieza por `sk-ant-`).
- `RateLimitError` (429) — límite por minuto o crédito insuficiente. Los límites dependen de tu **tier de uso**, que sube según acumulas gasto.
- `BadRequestError` (400) — causas comunes: olvidar `max_tokens`, mensajes que no alternan, modelo inexistente.
- `APIConnectionError` — red o caída.
- `InternalServerError` (500/529) — `529` = API sobrecargada. El SDK reintenta.

Configuras reintentos al crear el cliente: `Anthropic(max_retries=5)` o `max_retries=0` para desactivarlos. Como el SDK ya gestiona reintentos, normalmente no necesitas tu propio patrón; para lógica personalizada (*fallback* a otro proveedor) los desactivas — algo que haremos en la Sesión 3.

## Diferencias clave a recordar (vs OpenAI)

1. **`max_tokens` obligatorio** (opcional en OpenAI).
2. **Los mensajes deben alternar** `user`↔`assistant`. OpenAI es más flexible.
3. **No hay helper `output_text`** — siempre `content[0].text`.
4. **No hay timestamp** en la respuesta.
5. **El SDK de Anthropic reintenta solo**; el de OpenAI no.
6. **`temperature` llega a `1.0`** (a `2.0` en OpenAI).

---

# Parte 3 — El API de Gemini

## El SDK de Google Gen AI

> **Google Gen AI SDK** (`google-genai`) = el SDK unificado para los modelos Gemini. Funciona con la **Gemini Developer API** (acceso directo con API key) y con **Vertex AI** (vía Google Cloud). En el programa usamos la Developer API por su simplicidad: solo una key, sin proyecto en Google Cloud.

> ⚠️ El SDK anterior (`google-generativeai`) está **deprecado**. Todo el código usa `google-genai`, estándar desde 2025.

La interfaz principal es `client.models.generate_content()`.

## La llamada completa

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

Diferencias vs OpenAI/Anthropic: el *system prompt* va dentro de un objeto `config`, la entrada va en `contents`, el texto se lee con **`response.text`**, y **toda la configuración se agrupa en `GenerateContentConfig`**.

## `system_instruction`: dentro de `config`

Cumple la función del *system prompt*. Acepta **string** o **lista de strings** (cada una se trata como instrucción independiente, útil para modularizar):

```python
config=types.GenerateContentConfig(system_instruction=[
    "You are a senior software architect.",
    "Your audience is developers with 5+ years of experience.",
    "Always respond in Spanish, maximum 200 words, in prose.",
])
```

## `contents`: estructura de mensajes y el rol `model`

Acepta string, lista mixta o array de objetos `Content` con roles:

```python
contents=[
    types.Content(role="user", parts=[types.Part(text="What is a REST API?")]),
    types.Content(role="model", parts=[types.Part(text="A REST API is...")]),
    types.Content(role="user", parts=[types.Part(text="Difference with GraphQL?")]),
]
```

> **A diferencia de OpenAI y Anthropic (que usan `assistant`), Gemini usa `model`** como rol para las respuestas del modelo. Si usas `assistant`, obtienes un error.

## Conversación multi-turno

**Stateless.** Dos opciones:
- **A — Manual:** reconstruyes el historial con un array de `Content`.
- **B — Helper de chat:** `client.chats.create()` gestiona el historial (`chat.send_message(...)`, `chat.get_history()`). Es conveniencia del SDK: internamente sigue enviando el historial completo, con el mismo impacto en tokens.

## Parámetros (`GenerateContentConfig`)

Toda la configuración va dentro de `GenerateContentConfig` (no como argumentos separados):

| Parámetro | Notas |
|---|---|
| `system_instruction` | String o lista de strings. Opcional. |
| `temperature` | Rango `0.0`–`2.0` (como OpenAI, más amplio que Anthropic). |
| `max_output_tokens` | **Opcional** en Gemini. Si no se especifica, el modelo decide. |
| `top_p`, `top_k` | `top_k` en Gemini y Anthropic, no en OpenAI. |
| `candidate_count` | Nº de respuestas alternativas. Por defecto 1. |
| `stop_sequences` | Secuencias que detienen la generación. |
| `seed` | Resultados reproducibles (mismo seed + mismo input = misma respuesta). Útil para testing. |
| `safety_settings` | **Filtros de seguridad de contenido**, propios de Gemini. Pueden bloquear respuestas. Si el modelo rechaza generar, revisa esto. |
| `thinking_config` | `types.ThinkingConfig(thinking_budget=N)`. **Habilitado por defecto** en Gemini 2.5 Flash/Pro y 3 Pro. Los tokens de pensamiento se facturan como salida; reduce el budget o desactívalo si prima la velocidad. |

## Estructura de la respuesta

Objeto `GenerateContentResponse`:
- `response.text` — atajo al texto del primer candidato (≡ `output_text` / `content[0].text`).
- `candidates` — array (porque `candidate_count` permite varias). Con el valor por defecto (1), siempre uno.
- `candidates[0].finish_reason` — `STOP` (natural), `MAX_TOKENS` (cortado), `SAFETY` (bloqueado), `RECITATION` (posible copyright).
- `candidates[0].safety_ratings` — evaluación de seguridad por categoría.
- `model_version` — el snapshot exacto (p. ej. `gemini-2.5-flash-001`).

## Metadatos, tokens y coste

- **Gemini no devuelve ID de request ni timestamp** — genera los tuyos.
- `usage_metadata`:
  - `prompt_token_count` — entrada (≡ `input_tokens`).
  - `candidates_token_count` — salida (≡ `output_tokens`).
  - `thoughts_token_count` — razonamiento (con thinking); se factura como salida.
  - `cached_content_token_count` — servidos desde caché (tarifa reducida).
  - `total_token_count` — la suma.
- Gemini 2.5 Flash es de los más baratos del mercado; sin thinking, una llamada típica es comparable a `gpt-4o-mini`.

## Contar tokens antes de la llamada (exclusivo)

> **`count_tokens()`** = endpoint **gratuito** de Gemini para estimar el consumo **antes** de enviar la request. **Ni OpenAI ni Anthropic lo ofrecen como endpoint nativo** — ventaja exclusiva para control de costes previo.

## Manejo de errores

Excepciones del módulo `google.genai.errors`:
- `401 Unauthorized` — key no válida o no configurada (`GEMINI_API_KEY` o `GOOGLE_API_KEY`).
- `429 Resource Exhausted` — rate limit. Gemini mide tres dimensiones: **RPM** (requests/min), **TPM** (tokens/min) y **RPD** (requests/día). El free tier es muy restrictivo (10–15 RPM); habilitar billing los dispara.
- `400 Bad Request` — modelo inexistente, `role="assistant"` en vez de `role="model"`, o `contents` vacío.
- **`SAFETY` block** — no es error HTTP sino un `finish_reason`. El modelo generó pero los filtros bloquearon.
- `500/503 Server Error` — error de Google. Reintenta tras unos segundos.

> **A diferencia de Anthropic, el SDK de Gemini NO reintenta automáticamente** — debes implementarlo tú.

## Diferencias clave a recordar

1. **El rol del modelo es `"model"`, no `"assistant"`** — `"assistant"` produce error.
2. **Toda la configuración va dentro de `GenerateContentConfig`.**
3. **No hay ID de request ni timestamp** — genera los tuyos.
4. **Los filtros de seguridad pueden bloquear** sin error HTTP — revisa `finish_reason` y `safety_ratings`.
5. **`count_tokens()` es gratuito y exclusivo.**
6. **El SDK no reintenta** — implementa tu lógica.
7. **Thinking está on por defecto** en Gemini 2.5+ — consume tokens extra facturados como salida.

---

# Parte 4 — Parámetros en modelos de razonamiento

## Por qué son diferentes

Un modelo "normal" responde de una pasada. Un **modelo de razonamiento** (OpenAI GPT-5/o3/o4-mini; Anthropic Claude 4/4.5/4.6 con *extended thinking*) internamente **genera varias cadenas de razonamiento, las evalúa, descarta ramas malas y solo entonces produce la respuesta**. Como un alumno que hace borradores.

Ese proceso lo **calibra el proveedor**. Si tocaras ajustes tradicionales (`temperature`, `top_p`) romperías la calibración (p. ej., `temperature=0` colapsaría todas las ramas en una sola ruta *greedy*, anulando el beneficio). Por eso los proveedores **bloquean** varios parámetros de muestreo y meten **parámetros nuevos** (`reasoning_effort`, `verbosity`, `thinking`) como otra vía de control.

## OpenAI — modelos afectados

- **o-series:** `o1`, `o1-mini`, `o3`, `o3-mini`, `o3-pro`, `o4-mini`.
- **GPT-5:** `gpt-5`, `gpt-5-mini`, `gpt-5-nano`, `gpt-5.1`…`gpt-5.4` y variantes.
- **Codex:** `gpt-5-codex`, `gpt-5.2-codex`, `gpt-5.3-codex`.

**Bloqueados o restringidos:**

| Parámetro | Estado | Comportamiento |
|---|---|---|
| `temperature` | ❌ No soportado | Fijado en 1. Enviarlo da error. |
| `top_p` | ❌ No soportado | Fijado en 1. Enviarlo da error. |
| `presence_penalty` / `frequency_penalty` | ❌ No soportado | Fijados en 0. |
| `logprobs` / `top_logprobs` | ❌ No soportado | No exponen probabilidades de tokens. |
| `logit_bias` | ❌ No soportado | No se influye en la selección. |
| `n` | ⚠️ Restringido | Fijado en 1. Sin candidatos múltiples. |
| `max_tokens` | ⚠️ Deprecado | Usar `max_completion_tokens` (Chat) o `max_output_tokens` (Responses). |

**Parámetros nuevos:**

| Parámetro | En | Descripción |
|---|---|---|
| `reasoning_effort` / `reasoning.effort` | o1+, GPT-5+ | Cuánto "piensa": `minimal` (GPT-5+), `none` (GPT-5.2+), `low`, `medium` (default), `high`, `xhigh` (GPT-5.2+/Codex). Más esfuerzo = más calidad pero más coste y latencia. |
| `verbosity` | GPT-5+ | Longitud de la respuesta final sin tocar el razonamiento (`low`/`medium`/`high`). Reemplaza el control de longitud que antes se hacía con *prompt engineering*. |
| `previous_response_id` | Responses API | Pasa la cadena de pensamiento entre turnos (mejora calidad y caché). |

> **`system` → `developer`:** en o-series, `role:"system"` se trata como `role:"developer"`. El SDK lo gestiona, pero no uses ambos roles en la misma request.

## Anthropic — modelos con extended thinking

Afectados: Opus 4/4.1/4.5/4.6, Sonnet 4/4.5/4.6, Haiku 4.5. Las restricciones aplican **cuando se activa `thinking`**. Sin thinking aceptan los parámetros tradicionales (con las excepciones de abajo).

**Con thinking activado:**

| Parámetro | Estado | Comportamiento |
|---|---|---|
| `temperature` | ❌ No modificable | Enviarlo da error. |
| `top_k` | ❌ No modificable | No ajustable. |
| `top_p` | ⚠️ Restringido | Solo entre `0.95` y `1.0`. Más bajos fallan. |
| `tool_choice: "any"` o `"tool"` | ❌ No compatible | El *forced tool use* es incompatible con thinking. Usa `"auto"`. |
| Response pre-filling | ❌ No soportado | No puedes pre-rellenar el inicio de la respuesta. |

> **Restricción adicional en 4.5+ (incluso SIN thinking):** Sonnet 4.5 y Haiku 4.5 (y posteriores) hacen `temperature` + `top_p` **mutuamente excluyentes** — no puedes enviar ambos. **No existía en Claude 3.5**, así que código que funcionaba con 3.5 puede romperse al migrar.

**Parámetros nuevos:**

| Parámetro | En | Descripción |
|---|---|---|
| `thinking` | Claude 4+ con thinking | `{"type":"enabled","budget_tokens":N}`. El budget es objetivo, no límite estricto. Mínimo 1024. |
| `interleaved-thinking-2025-05-14` (beta header) | Claude 4+ | Thinking intercalado con *tool use*: piensa entre llamadas a herramientas. |
| `context-management-2025-06-27` (beta header) | Sonnet/Haiku/Opus 4+ | Habilita `clear_thinking_20251015` para limpiar thinking blocks de turnos anteriores y reducir contexto. |

## Tabla resumen: ¿qué sigue funcionando?

| Parámetro | OpenAI clásicos (`gpt-4o`/`mini`) | OpenAI razonamiento | Anthropic clásicos (`3.5`) | Anthropic 4.5+ sin thinking | Anthropic 4+ con thinking |
|---|---|---|---|---|---|
| `temperature` | ✅ | ❌ | ✅ | ⚠️ (no con `top_p`) | ❌ |
| `top_p` | ✅ | ❌ | ✅ | ⚠️ (no con `temperature`) | ⚠️ (solo 0.95–1.0) |
| `top_k` | — | — | ✅ | ✅ | ❌ |
| `presence_penalty` | ✅ | ❌ | — | — | — |
| `frequency_penalty` | ✅ | ❌ | — | — | — |
| `logprobs`/`top_logprobs` | ✅ | ❌ | — | — | — |
| `logit_bias` | ✅ | ❌ | — | — | — |
| `n > 1` | ✅ | ❌ | — | — | — |
| `seed` | ✅ | ✅ | ❌ | ❌ | ❌ |
| `stop_sequences`/`stop` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `max_tokens`/`max_output_tokens` | ✅ | ✅ (`max_output_tokens`/`max_completion_tokens`) | ✅ (oblig.) | ✅ (oblig.) | ✅ (oblig.) |
| `reasoning_effort` | ❌ | ✅ | — | — | — |
| `verbosity` | ❌ | ✅ (GPT-5+) | — | — | — |
| `thinking` | — | — | ❌ | — | ✅ |
| Forced tool use | ✅ | ✅ | ✅ | ✅ | ❌ |
| Response pre-fill | — | — | ✅ | ✅ | ❌ |

Leyenda: ✅ soportado · ❌ no · ⚠️ con restricciones · — no aplica.

## Implicaciones prácticas

1. **Sobre modelos no-razonamiento, todo igual.** Usamos `gpt-4o-mini` y `claude-haiku-4-5-20251001`. Haiku 4.5 tiene la restricción de no combinar `temperature` y `top_p`, pero como solo usamos `temperature`, no nos afecta.
2. **Si migras a razonamiento, revisa tu código:**
   - **OpenAI (GPT-5, o3, o4-mini):** elimina `temperature`, `top_p`, `frequency_penalty`, `presence_penalty`, `logprobs`, `logit_bias`. Sustituye por `reasoning_effort` y `verbosity`.
   - **Anthropic con thinking:** elimina `temperature` y `top_k`. `top_p` solo en `0.95–1.0`. Sin forced tool use ni pre-filling.
3. **El "coste del razonamiento" se factura como salida.** Tanto `reasoning_tokens` (OpenAI) como `thinking_tokens` (Anthropic) van al precio de salida aunque no se vean. `reasoning_effort: "high"` puede consumir 10x más tokens de salida que `"minimal"` para la misma pregunta.

> **Regla mnemotécnica:** *los modelos de razonamiento te quitan el control del muestreo y te dan control sobre el razonamiento.* Pierdes `temperature`/`top_p`/penalties; ganas `reasoning_effort`+`verbosity` (OpenAI) o `thinking.budget_tokens` (Anthropic). Es un intercambio deliberado.

---

# Parte 5 — Tokenización: conceptos avanzados

## El problema que resuelve

> **Tokenización** = el proceso que convierte texto legible en una secuencia de IDs numéricos que el modelo puede procesar, y viceversa. Los modelos **no leen texto**: un *transformer* solo opera sobre números enteros.

El string `"How long would a database migration take?"` llega al modelo como algo como `[4438, 1317, 1053, 264, 7316, 12507, 1935, 30]`. Cada número es un **token**.

> Para un AI Engineer, los tokens son la **unidad de medida fundamental del stack**: longitud del prompt, idioma, formato de datos… todo se traduce en tokens, y **los tokens se traducen en dinero y latencia**.

## De texto a números: el flujo

Tres fases:
- **Fase 1 — Codificación a bytes (UTF-8):** `A` = 1 byte, `ñ` = 2 bytes, 🚀 = 4 bytes. **Los idiomas no-ASCII (español, chino, árabe) consumen más bytes por carácter.**
- **Fase 2 — Pre-tokenización:** divide el texto con reglas (regex) por espacios, puntuación y categorías. Garantiza que ciertos *merges* no crucen fronteras (un número nunca se fusiona con una letra).
- **Fase 3 — BPE:** dentro de cada fragmento, aplica una tabla de *merges* aprendida para combinar bytes en tokens cada vez más grandes → la secuencia de IDs.

```
Text:      'PostgreSQL migration'
Token IDs: [5765, 48528, 12507]
  5765 → 'Postgre'  ·  48528 → 'SQL'  ·  12507 → ' migration'  (el espacio anterior es parte del token)
```

Que `' migration'` incluya el espacio anterior es una decisión de diseño del tokenizador, no un error.

## BPE: el algoritmo que domina la industria

> **BPE (Byte Pair Encoding)** = el algoritmo de tokenización de GPT-2/3/4/5, Llama, Mistral y casi todos los LLMs actuales. Propuesto en 1994 como compresión, adaptado a NLP en 2015.

El **entrenamiento del tokenizador** (independiente del entrenamiento del modelo) es iterativo:
1. Vocabulario base de 256 tokens (uno por byte posible).
2. Escanear un corpus y contar la frecuencia de cada par adyacente.
3. Fusionar el par más frecuente en un token nuevo y añadirlo.
4. Repetir hasta el tamaño de vocabulario deseado.

El resultado es una **tabla de merges** ordenada: esa tabla **es** el tokenizador.

| Modelo | Encoding | Vocabulario | Año |
|---|---|---|---|
| GPT-2 | `gpt2` | ~50K | 2019 |
| GPT-3.5/4 | `cl100k_base` | ~100K | 2023 |
| GPT-4o | `o200k_base` | ~200K | 2024 |

Vocabulario más grande = secuencias más cortas (menos cómputo) y mejor cobertura multilingüe, pero matrices de embedding mayores. Se han **cuadruplicado en tres años**.

Otros algoritmos: **WordPiece** (BERT; merge por máxima verosimilitud, no frecuencia), **Unigram** (T5/ALBERT; empieza con un vocabulario enorme y elimina tokens, captura mejor terminaciones como `-ing`/`-tion`/`-mente`). **Si usas OpenAI, Anthropic u open source, estás usando BPE.**

## Patrones que te afectan en producción

- **El español consume más tokens que el inglés:** típicamente **20–40% más** para el mismo contenido; japonés/chino el doble o más. El corpus de entrenamiento está dominado por inglés. *Decisión:* algunos equipos escriben los system prompts en inglés (aunque respondan en español) para ahorrar; un prompt de 200 tokens en español vs 150 en inglés acumula 1.000 tokens extra en 20 turnos. **Regla: 1.000 tokens ≈ 750 palabras en inglés ≈ 600 en español.**
- **El código es eficiente en tokens:** keywords (`def`, `return`, `SELECT`, `FROM`) son frecuentes y tienen tokens dedicados. Los nombres de tu dominio se fragmentan más. 100 líneas de Python ≈ 300–500 tokens.
- **Espacios, saltos de línea e indentación son tokens:** `"Hello"` y `" Hello"` (con espacio) son tokens **distintos**. Un JSON compacto consume bastante menos que el mismo con *pretty-print*. *Implicación:* inyecta datos estructurados en formato compacto.
- **Los números se tokenizan de forma inconsistente:** `"100"` puede ser un token y `"101"` partirse en `"10"`+`"1"`. Por eso los LLMs son malos en aritmética: nunca ven los dígitos alineados, ven `"1234"` como una unidad opaca. *Implicación:* **nunca dependas de un LLM para cálculos aritméticos.**
- **Tokens especiales:** marcan estructura (inicio/fin de mensaje, separadores de roles, delimitadores de herramientas: `<|endoftext|>`, `<|im_start|>`, `<|im_end|>`). Invisibles (el SDK los gestiona) pero **cuentan** en `usage.input_tokens` — por eso la API reporta algo más que tokenizar solo tu texto.

## Tokenización y ventanas de contexto

> **Ventana de contexto** = el máximo de tokens en una sola llamada. Incluye **todo**: system prompt + historial + entrada del usuario + **respuesta del modelo**. La respuesta también cuenta.

| Modelo | Ventana | ≈ Páginas |
|---|---|---|
| `gpt-4o-mini` | 128.000 | ~190 |
| `gpt-5.4` | 200.000 | ~300 |
| `claude-haiku-4-5` | 200.000 | ~300 |
| `claude-sonnet-4-6` | 200.000 | ~300 |
| `gemini-2.5-flash` | ~1.000.000 | ~1.500 |
| `gemini-3-pro` | ~2.000.000 | ~3.100 |

(≈ 1 página ≈ 500 palabras ≈ 670 tokens.)

**Cómo se llena en una conversación:** cada turno acumula los tokens anteriores; el system prompt **se reenvía con cada llamada**. En el turno 9 pagas el system prompt por novena vez, más todo el historial. Una conversación de 20 turnos con system prompt de 500 tokens acumula 10.000 tokens extra — coste puro sin valor. Mitigaciones:
- **Prompt caching** (Anthropic 90% en cache hits; OpenAI también).
- **Truncado de historial** (solo los últimos N turnos).
- **Resumen de turnos anteriores.**
- **`previous_response_id`** (OpenAI gestiona el contexto y optimiza caché).

**Contar tokens antes de enviar:** Gemini con `count_tokens()` gratuito; para OpenAI, `tiktoken` localmente. La estimación local es aproximada (la API añade tokens especiales que no se replican), pero suficiente para estimar coste y verificar que no excedes la ventana.

## Tokenización y coste: las matemáticas

- **Asimetría input/output:** la salida es **más cara** que la entrada (ratio **3x–10x**) porque cada token de salida requiere una pasada completa, mientras los de entrada se procesan en paralelo. *Implicación:* optimizar la **longitud de las respuestas** pesa más en tu factura que optimizar el prompt. Un `"Maximum 200 words"` no es solo UX, es una palanca de coste.
- **Proyección a escala:** entre `gpt-4o-mini` y `gpt-5.4` para el mismo volumen puede haber **10–30x** en coste mensual. Muchas veces el barato basta. **La elección de modelo es una decisión de negocio.**
- **Prompt caching:** si una porción del input (system prompt, contexto inyectado) se repite, esos tokens se sirven desde caché con descuento. Especialmente relevante en **CAG y RAG**. Se profundiza en la Sesión 3.

## Limitaciones fundamentales

- **El modelo no ve letras:** pedirle contar letras o deletrear al revés contradice su representación interna. `"Strawberry"` puede ser un token (ID 92850); el modelo ve el 92850, no S-t-r-a-w-b-e-r-r-y.
- **No es uniforme entre proveedores:** cada uno entrena su tokenizador con su corpus → el mismo texto da longitudes distintas. **No puedes usar `tiktoken` para estimar exactamente Anthropic o Gemini.** Anthropic típicamente produce 5–15% más tokens que OpenAI en inglés; para Gemini, usa `count_tokens()`.
- **Tokens "glitch":** en 2023 ciertos tokens producían comportamiento errático en GPT-3.5/4. El caso famoso, `"SolidGoldMagikarp"` — un username de Reddit frecuente en el corpus del tokenizador pero tan raro en el del modelo que su embedding quedó aleatorio. **Causa raíz: los datos de entrenamiento del tokenizador y del modelo no son los mismos.** `o200k_base` ha eliminado la mayoría, pero persiste como limitación arquitectural.

## Resumen: lo que un AI Engineer necesita saber

1. **Los tokens no son palabras.** Fragmentos de longitud variable (BPE). Una palabra puede ser 1 token o 5.
2. **El idioma importa.** Español 20–40% más que inglés.
3. **La salida es 3–6x más cara que la entrada.** Controlar la longitud de respuestas pesa más que optimizar el prompt.
4. **Cada turno reenvía todo el historial.** El coste crece **cuadráticamente**. Gestionar el contexto es requisito de viabilidad económica, no optimización.
5. **Los tokenizadores varían entre proveedores.** `tiktoken` solo aproxima Anthropic y Gemini.
6. **El formato de tus datos consume tokens.** JSON pretty-print/indentación gastan sin aportar.
7. **El modelo no ve letras ni dígitos individuales.** No le delegues aritmética ni manipulación de strings.

---

# Parte 6 — Comparación de modelos 2026

> ⚠️ Precios y modelos cambian con frecuencia. Esto refleja el mercado a **1 de abril de 2026**. Consulta siempre las páginas oficiales antes de decisiones de producción.

## Panorama de proveedores

**Los cinco grandes:**
- **OpenAI** — líder en amplitud de catálogo. GPT-5.4 (marzo 2026) cubre desde Nano (ultra-barato) a Pro (premium con razonamiento). Pionero en *computer use* y herramientas integradas. El mayor ecosistema de devs.
- **Anthropic** — calidad y seguridad. Claude (Haiku 4.5, Sonnet 4.6, Opus 4.6), tres tiers claros. Opus 4.6 lidera benchmarks de software (SWE-Bench Verified). Hasta 1M tokens en Opus/Sonnet. Fuerte en prompt caching.
- **Google** — ventaja en su ecosistema (Workspace, Cloud, Vertex AI). Gemini de Flash (ultra-barato) a Pro. Multimodal nativo fuerte (texto, imagen, audio, vídeo). Precios agresivos en entrada.
- **xAI (Grok)** — Grok 4 en premium; Grok 4.1 Fast con la **ventana más grande del mercado (2M tokens)**. Datos en tiempo real de X. Fuerte en razonamiento científico.
- **DeepSeek** — el disruptor chino de precios. V3.2 da calidad comparable a modelos 50–100x más caros, a **$0.14–$0.28/MTok**. Open source. *Contrapartida:* datos por servidores en China → problema de compliance.

**Otros relevantes:**
- **Mistral** (Francia) — open source Apache 2.0. Small y Medium con gran calidad/precio para deployments con control total de datos. Relevante para GDPR.
- **Meta (Llama)** — open source de referencia. Scout y Maverick gratis; requieren infra propia o Together AI / Fireworks / Amazon Bedrock.
- **Cohere** — especializado en RAG empresarial y búsqueda semántica. Command R+ con *retrieval* nativo. Fuerte en multilingüe.

## Modelos principales por proveedor (precio por 1M tokens)

**OpenAI:**

| Modelo | Input | Output | Contexto | Caso de uso |
|---|---|---|---|---|
| GPT-5.4 | $2.50 | $15.00 | 1M | Flagship. Coding, computer use, razonamiento. |
| GPT-5.4 Pro | $30.00 | $180.00 | 1M | Razonamiento extendido. Premium. |
| GPT-5.4 mini | $0.75 | $4.50 | 400K | Rápido y capaz. Coding, agentes, multimodal. |
| GPT-5.4 nano | $0.20 | $1.25 | 400K | Ultra-barato. Clasificación, extracción, subagentes. Solo API. |
| GPT-5.2 | $1.75 | $14.00 | 400K | Generación anterior. Se retira en junio 2026. |
| GPT-5 mini | $0.25 | $2.00 | 400K | Buen balance coste/calidad. |
| GPT-5 nano | $0.05 | $0.40 | 400K | El más barato de OpenAI con calidad aceptable. |
| GPT-4o-mini | $0.15 | $0.60 | 128K | Legacy. Muy barato pero superado por GPT-5 nano. |

*Nota:* precios se duplican para requests > 272K tokens en GPT-5.4/Pro. Batch API 50% off. Cached inputs hasta 90% off. **API: Responses (recomendada) + Chat Completions (indefinida).**

**Anthropic (Claude):**

| Modelo | Input | Output | Contexto | Caso de uso |
|---|---|---|---|---|
| Claude Opus 4.6 | $5.00 | $25.00 | 1M | Líder en ingeniería de software. Premium. |
| Claude Sonnet 4.6 | $3.00 | $15.00 | 1M | Muy buen equilibrio. Extended thinking. |
| Claude Sonnet 4.5 | $3.00 | $15.00 | 1M | Generación anterior de Sonnet. |
| Claude Haiku 4.5 | $1.00 | $5.00 | 200K | Rápido y económico. Volumen alto, complejidad media. |

*Nota:* prompt caching 90% off en cache reads (solo 10% del base); cache writes 1.25x base. Batch API 50% off. **API: Messages (única).**

**Google (Gemini):**

| Modelo | Input | Output | Contexto | Caso de uso |
|---|---|---|---|---|
| Gemini 3 Pro | $2.00 | $12.00 | 66K | Última gen. Multimodal fuerte (incl. generación de imágenes). |
| Gemini 3 Flash | $0.50 | $3.00 | 1M | Rápido y barato. Excelente para volumen. |
| Gemini 2.5 Pro | $2.50 | $15.00 | 1M | Generación anterior. Fuerte en razonamiento y multimodal. |
| Gemini 2.5 Flash | $0.15 | $0.60 | 1M | Ultra-barato con 1M de contexto. Procesamiento masivo. |

*Nota:* context caching 90% off en cache reads. **API: Gemini API (compatible con formato OpenAI vía adaptadores).**

**xAI (Grok):** Grok 4 ($3/$15, 256K) · Grok 4.1 Fast ($0.20/$0.50, **2M** — el mayor del mercado). API compatible con OpenAI.

**DeepSeek:** V3.2 ($0.14/$0.28, 164K — disruptor) · R1 ($0.55/$2.19, 128K — razonamiento, competidor de o3/o4-mini a coste mínimo). Open source self-hosting; datos en China.

**Mistral:** Large ($2/$6, 128K) · Small 4 ($0.10/$0.30, 128K, Apache 2.0) · Medium ($0.40/$1.10, 64K). Open source permisivo, ideal self-hosting con control total (GDPR).

**Meta (Llama):** Maverick ($0.15/$0.60, 1M) · Scout ($0.08/$0.30, 1M) · Llama 3.3 70B (gratuito* vía OpenRouter, 128K). Self-hosting gratuito pero requiere infra GPU.

## ¿Qué modelo elegir? (por caso de uso)

| Caso de uso | Recomendación principal | Alternativa económica |
|---|---|---|
| Chatbot / asistente | Claude Sonnet 4.6 o GPT-5.4 | Claude Haiku 4.5 o GPT-5.4 mini |
| Generación de código | Claude Opus 4.6 o GPT-5.4 | GPT-5.4 mini o DeepSeek V3.2 |
| Documentos largos | Gemini 2.5 Flash (1M) o Claude Sonnet 4.6 | Grok 4.1 Fast (2M) |
| Clasificación / extracción | GPT-5.4 nano o GPT-5 nano | DeepSeek V3.2 o Mistral Small 4 |
| Razonamiento complejo | Claude Opus 4.6 o GPT-5.4 Pro | DeepSeek R1 |
| Procesamiento masivo (batch) | DeepSeek V3.2 o Gemini 2.5 Flash | GPT-5 nano con Batch API |
| Prototipado rápido | GPT-5.4 nano o Gemini 2.5 Flash | Llama 3.3 70B (gratuito) |
| Compliance GDPR estricto | Mistral o Llama (self-hosted) | Anthropic (datos en US/EU) |

## Conceptos clave de pricing

- **Tokens = la unidad.** Se factura por tokens. Un token ≈ 4 caracteres en inglés (~0.75 palabras); en español peor (tildes, ñ, palabras largas). **Regla: 1.000 tokens ≈ 750 palabras en inglés ≈ 600 en español.**
- **Asimetría input/output:** salida 3x–10x más cara. Optimizar la longitud de respuestas pesa más que optimizar prompts.
- **Prompt caching** (reutiliza cálculos de tokens repetidos):

  | Proveedor | Cache read (descuento) | Cache write (sobrecoste) |
  |---|---|---|
  | OpenAI | 50–90% | Sin sobrecoste (automático) |
  | Anthropic | 90% | 25% sobrecoste |
  | Google | 90% | Sin sobrecoste |

  Especialmente relevante en CAG y RAG donde el system prompt y el contexto base se repiten.
- **Batch API:** todos los grandes ofrecen proceso asíncrono (< 24h) con **50% de descuento**. Ideal para masivo sin tiempo real.

## Agregadores y routers

Para proyectos multi-proveedor (como haremos):
- **OpenRouter** — SaaS que da acceso a 500+ modelos con una sola API y un solo billing. Cobra **5.5% sobre el precio base**. Sin cuentas separadas. Ideal para prototipado. Incluye modelos gratuitos (Llama 3.3, Gemma 3, DeepSeek R1).
- **LiteLLM** — librería open source que unifica 100+ proveedores en formato OpenAI. **Self-hosted, sin markup.** Load balancing, fallback automático, tracking de costes por equipo. Más control, más setup. Ideal para producción.

Ambas las usamos al construir la **capa de abstracción de proveedores**.

## Tendencias del mercado

- **Los precios caen rápido:** ~80% de bajada entre principios de 2025 y 2026. Lo que hoy cuesta $0.15/MTok costaba $0.60 hace un año.
- **Multi-modelo es el estándar:** barato para tareas simples (clasificación, routing), mid-tier para la mayoría, premium para casos difíciles. **Reduce costes 60–80%** frente a usar siempre el premium.
- **El contexto crece:** de 4K (GPT-3.5, 2023) a 1–2M (2026). Habilita CAG más potente y reduce el *chunking* agresivo en RAG.
- **Open source cierra la brecha:** Llama 4, DeepSeek V3.2, Qwen 3 compiten con comerciales 10–50x más caros. Para empresas con infra GPU, el self-hosting es cada vez más viable.

---

# Chuleta de una página (lo imprescindible)

- **Estructura universal:** toda llamada = **instrucciones + entrada + configuración → texto + metadatos**. Lo que cambia entre proveedores es el envoltorio.
- **OpenAI (Responses):** `instructions` + `input` + `output_text`. Stateless con `previous_response_id`. Dos APIs (Responses recomendada, Chat Completions el patrón común).
- **Anthropic (Messages):** `system` + `messages` (alternan `user`↔`assistant`) + `content[0].text`. **`max_tokens` obligatorio.** Sin timestamp. SDK reintenta solo. `temperature` máx `1.0`.
- **Gemini (`generate_content`):** todo en `GenerateContentConfig`; rol **`model`** (no `assistant`); `response.text`. `count_tokens()` gratis. Sin ID/timestamp. Filtros de seguridad pueden bloquear. SDK **no** reintenta. Thinking on por defecto en 2.5+.
- **Modelos de razonamiento:** te **quitan** muestreo (`temperature`, `top_p`, penalties…) y te **dan** razonamiento (`reasoning_effort`/`verbosity` en OpenAI, `thinking.budget_tokens` en Anthropic). El razonamiento se factura como **output**.
- **Tokenización:** tokens ≠ palabras (BPE). Español 20–40% más caro que inglés. Output 3–10x más caro que input. Cada turno reenvía todo el historial (coste cuadrático). JSON compacto > pretty-print. El modelo no ve letras ni dígitos → no le delegues aritmética. Tokenizadores distintos por proveedor (`tiktoken` solo aproxima OpenAI).
- **Mercado 2026:** 5 grandes (OpenAI, Anthropic, Google, xAI, DeepSeek) + open source (Mistral, Llama) + agregadores (OpenRouter, LiteLLM). Multi-modelo = estándar (−60/80% coste). Prompt caching hasta 90% off. Batch API 50% off. Contexto hasta 1–2M. **La elección de modelo es una decisión de negocio.**

---

## Cómo conecta con nuestro ejercicio y con el directo

Esta sesión es la **base conceptual de todo el stack**:
- **Por qué separamos `instructions`/`system` del `input`/`messages`:** es la base de la arquitectura **CAG** — el desarrollador controla el comportamiento (prompt fijo), el usuario solo aporta su pregunta y nunca ve las instrucciones.
- **Por qué usamos `gpt-4o-mini` y `claude-haiku-4-5`:** relación calidad/precio. No son de razonamiento, así que todos los parámetros tradicionales (`temperature`, `max_tokens`…) funcionan sin restricciones.
- **Por qué la telemetría de tokens importa:** tokens = dinero, la salida es más cara que la entrada, y el coste crece con cada turno. Medir tokens no es opcional.
- **Por qué la capa de abstracción de proveedores (Sesión 3) tiene sentido:** las tres APIs hacen lo mismo con envoltorios distintos (`assistant` vs `model`, `output_text` vs `content[0].text`, `max_tokens` opcional vs obligatorio, reintentos o no). Unificarlas detrás de una interfaz común —o usar LiteLLM— permite cambiar de proveedor sin reescribir el producto.
