# Pre-session 04 — Implementación

Documento de referencia sobre los cambios introducidos en la rama `pre-session-04`. Cubre tanto el servicio de IA (`estimator/`) como la nueva interfaz Angular (`estimator-frontend/`) y la configuración de Docker. Está pensado para que se entienda sin conocer el código previo: cada decisión va acompañada de una explicación breve de qué problema resuelve.

---

## 1. Punto de partida y objetivo

Al cerrar la sesión 03 el estimator funcionaba así:

- El usuario escribía en un chat libre la transcripción de una reunión y pulsaba **Enviar**.
- El backend en FastAPI tomaba ese texto, lo metía como contenido del mensaje `user` y enviaba al LLM (OpenAI o Anthropic) un único *prompt* construido como `f-string` dentro del propio código.
- El frontend era una app de Streamlit con interfaz tipo chat.

Esta arquitectura tenía dos problemas que vienen de la misma decisión:

1. **El usuario "prompteaba" libremente.** Cualquier instrucción ambigua o demasiado breve daba resultados pobres y muy variables. Como el dominio (estimaciones de software) es acotado, dejar el campo abierto era perder calidad gratis.
2. **El prompt vivía como string dentro del código.** Cambiar un ejemplo o ajustar el tono obligaba a tocar el archivo Python, hacer un commit y desplegar. Tampoco había forma de probar en paralelo dos versiones del prompt.

El ejercicio pedía resolver ambos problemas:

- Sustituir el textarea libre por un **formulario tipado** con campos discretos.
- Sacar el prompt a **plantillas Jinja2 versionadas** dentro de una carpeta `prompts/v1/`.
- Refactorizar el endpoint para que reciba el formulario tipado y devuelva una respuesta también tipada.
- Añadir **tests de plantilla** que se ejecuten en milisegundos sin llamar al LLM.

A esto se añade una decisión propia: nuestro stack de frontend es **Angular + TypeScript**, no Streamlit. Por tanto la parte de cliente se ha rehecho en Angular 19 con Angular Material en lugar de portar el código de Streamlit.

---

## 2. Cambios en `estimator/` (servicio FastAPI)

### 2.1 Contrato tipado entre cliente y servicio (`app/schemas/estimation.py`)

Antes existía un único `EstimationRequest` con un campo `transcription: str`. Eso significaba que el LLM tenía que adivinar a partir del texto qué tipo de proyecto era, cuánto detalle se quería y en qué formato presentar la respuesta.

Ahora el request se compone de cuatro campos, tres de ellos enumerados:

```python
class ProjectType(str, Enum):
    MOBILE_APP = "mobile_app"
    WEB_SAAS = "web_saas"
    INTERNAL_TOOL = "internal_tool"
    DATA_PIPELINE = "data_pipeline"

class DetailLevel(str, Enum):
    SUMMARY = "summary"
    MEDIUM = "medium"
    DETAILED = "detailed"

class OutputFormat(str, Enum):
    PHASES_TABLE = "phases_table"
    LINE_ITEMS = "line_items"
    NARRATIVE = "narrative"

class EstimationRequest(BaseModel):
    description: str = Field(min_length=20, max_length=2000)
    project_type: ProjectType
    detail_level: DetailLevel
    output_format: OutputFormat
```

Para alguien no técnico: **enum** es una lista cerrada de valores válidos. Igual que un desplegable de un formulario web. Pydantic v2 valida automáticamente que el cliente envíe uno de los valores permitidos; si no lo hace, FastAPI devuelve un error `422 Unprocessable Entity` *antes* de llegar al LLM.

La respuesta también es estricta:

```python
class EstimationResponse(BaseModel):
    text: str
    prompt_version: str
    model: str | None = None
    provider: str | None = None
    usage: TokenUsage | None = None
```

`prompt_version` se devuelve siempre. Es información operativa: si una estimación sale rara, podemos rastrear con qué versión del prompt se generó.

### 2.2 Plantillas Jinja2 versionadas (`app/prompts/`)

La estructura nueva es:

```
app/prompts/
├── __init__.py
├── loader.py
└── estimation/
    └── v1/
        ├── system.j2
        ├── user.j2
        └── examples.j2
```

**Qué es Jinja2.** Un motor de plantillas para Python. Permite escribir un texto que contiene "huecos" (`{{ variable }}`) y bloques condicionales (`{% if … %}{% endif %}`). El motor toma la plantilla, le pasa un contexto con valores reales y produce un texto final. Es la misma idea que un mail combinado de Word, llevada a producción.

**Por qué versionar (`v1/`, `v2/`, …).** El prompt es un activo del producto, igual que el código. Si cambiamos el tono o añadimos un ejemplo nuevo, queremos:

- Poder comparar antes/después sin perder la versión anterior.
- Permitir un *rollback* inmediato si la nueva versión empeora resultados.
- Hacer A/B testing entre dos versiones simultáneamente.

Por eso cada versión vive en su propia subcarpeta. Cambiar de versión es una decisión a nivel de petición (un `?prompt_version=v2` en la URL), no un despliegue.

**Contenido de cada plantilla:**

- `system.j2` — Define el rol del modelo ("eres un consultor senior…"), las reglas generales y, según el formato y el nivel de detalle elegidos, añade o no instrucciones específicas. Al final incluye los ejemplos *few-shot* con `{% include "examples.j2" %}`.
- `user.j2` — Es el bloque que envuelve la descripción del proyecto del usuario, encapsulada dentro de etiquetas `<project_description>…</project_description>` para que sea fácil de localizar en los logs y para reducir el riesgo de *prompt injection*.
- `examples.j2` — Tres ejemplos de estimaciones bien formadas (uno por tipo de proyecto, distintos a los del enunciado del ejercicio). Cumplen la función de *few-shot learning*: el modelo aprende el formato esperado mirando los ejemplos.

### 2.3 El loader (`app/prompts/loader.py`)

Toda la lógica de renderizado vive en una función pública:

```python
def render_estimation_prompt(
    request: EstimationRequest, version: str = "v1"
) -> tuple[str, str]:
    ...
    return system, user
```

Devuelve la dupla `(system, user)` lista para entregar al LLM. El resto del código no necesita saber nada de Jinja2 ni de qué carpeta vive cada versión.

Tres opciones de Jinja2 elegidas con intención:

- **`StrictUndefined`** — Si una variable del template no está en el contexto del render, Jinja lanza una excepción. Sin esto, una variable mal escrita renderiza como cadena vacía y nadie se entera. Esta opción convierte un bug silencioso en un test que falla.
- **`trim_blocks=True` y `lstrip_blocks=True`** — Eliminan los saltos de línea y espacios alrededor de los bloques `{% … %}`. Sin esto, los condicionales dejan líneas en blanco enormes y el prompt final queda lleno de "ruido" que no aporta nada pero gasta tokens.
- **`@lru_cache`** sobre el constructor del environment — Jinja2 cachea las plantillas compiladas; reutilizar el environment evita reabrir y reanalizar los `.j2` en cada petición.

### 2.4 Endpoints (`app/routers/estimations.py`)

Dos endpoints reciben el mismo `EstimationRequest` y aceptan un parámetro de query `?prompt_version=v1` (por defecto `v1`):

- `POST /api/v1/estimate` — Llamada bloqueante. Devuelve la `EstimationResponse` cuando el LLM termina.
- `POST /api/v1/estimate/stream` — Streaming NDJSON. Cada línea es un JSON independiente:
  - `{"prompt_version": "v1"}` — Primera línea, anuncia la versión usada.
  - `{"t": "trozo de texto"}` — Tokens según van llegando.
  - `{"done": true, "model": "…", "provider": "…", "usage": {…}}` — Última línea con metadatos.

**Qué es NDJSON.** *Newline-delimited JSON*: un JSON por línea, sin coma entre objetos. Es trivial de parsear en streaming porque cada `\n` indica un objeto completo, sin tener que esperar a leer el array entero.

Ambos endpoints llaman a `render_estimation_prompt(request, version=prompt_version)` antes de invocar al LLM. El servicio LLM recibe `(system, user)` ya renderizados; no sabe nada del formato del prompt ni de las plantillas.

### 2.5 Wrapper de proveedores (`app/services/llm_service.py`)

El wrapper de OpenAI/Anthropic ya existía en sesión 03. Lo único que ha cambiado es la firma:

```python
def generate_estimation(system_prompt: str, user_message: str) -> dict: ...
def stream_estimation(system_prompt: str, user_message: str) -> Generator[bytes, None, None]: ...
```

Antes recibía `transcription` y construía el system prompt dentro. Ahora recibe los dos mensajes ya hechos y simplemente los reenvía al SDK del proveedor con los roles `system` y `user` separados. Esto es importante porque:

- **Separar `system` y `user` es la forma correcta de hablar con un LLM.** Concatenar ambos en un único mensaje de usuario funciona pero confunde al modelo: las instrucciones del sistema y la entrada del usuario quedan al mismo nivel.
- **El wrapper deja de tener responsabilidades de plantilla.** Cumple solo una función: hablar con el proveedor.

### 2.6 Tests de plantilla (`tests/prompts/test_estimation_v1.py`)

Cinco tests, todos puramente sintéticos (sin llamar al LLM, ejecución en milisegundos):

1. **`test_user_template_includes_description_verbatim`** — Verifica que la descripción del usuario aparece tal cual dentro del bloque `<project_description>`. Es la prueba de que el dato del cliente llega al modelo sin manipulación inesperada.
2. **`test_phases_table_keyword_appears_only_when_selected`** — Cuando `output_format=phases_table`, el system prompt menciona `phases_table` y `confidence_pct`. Cuando es `narrative`, no debe aparecer ninguna de las dos. Garantiza que el condicional Jinja2 funciona.
3. **`test_detailed_level_adds_assumptions_instruction`** — Con `detail_level=detailed`, el prompt incluye la instrucción de enumerar asunciones por fase. Con `summary`, no.
4. **`test_examples_are_embedded_via_include`** — Los tres ejemplos (`EXAMPLE 1`, `EXAMPLE 2`, `EXAMPLE 3`) aparecen en el system prompt renderizado. Es la prueba del `{% include %}`.
5. **`test_unknown_version_raises`** — Pedir `version="v999"` lanza una excepción. Garantiza que no se puede caer en una versión inexistente sin enterarse.

**Qué cubre un test de plantilla.** Cubre la *construcción* del prompt: que los condicionales funcionan, que las variables se sustituyen correctamente, que los includes se resuelven. **No cubre** el comportamiento del modelo: si el modelo ignora la instrucción "lista asunciones por fase", eso es un problema del prompt en sí, no del template engine. Los tests del modelo (eval suite) son otra cosa.

### 2.7 Dependencias

Se eliminan: `streamlit`, `httpx` (este último solo era usado por el cliente Streamlit; pytest lo trae igualmente como dev dep).

Se añade: `jinja2`.

El `uv.lock` se ha regenerado con `uv lock` para reflejar el cambio. La imagen Docker queda más ligera al desaparecer Streamlit y sus dependencias indirectas (pandas, pyarrow, pillow, etc.).

---

## 3. Cambios en `estimator-frontend/` (cliente Angular)

### 3.1 Por qué Angular y no Streamlit

Streamlit es excelente para prototipar y demos internas, pero no es nuestro framework de producto. Nuestro stack es Angular + TypeScript y todo lo que va a entrar en una arquitectura real (autenticación, *routing*, *state management*, *i18n*, etc.) ya está resuelto en Angular pero habría que reinventarlo en Streamlit.

Aprovechamos este ejercicio para mover la pieza al stack correcto desde el principio.

### 3.2 Stack elegido

- **Angular 19** con *standalone components*. Es la última mayor estable y elimina la necesidad de `NgModule`. Cada componente declara sus dependencias en su propio `imports`.
- **Angular Material** para los componentes de UI (form fields, selects, botones, cards, toolbar, progress bar). Material trae validación visual, accesibilidad y temas listos.
- **Signals** (`signal()`, `update()`, `set()`) en lugar de RxJS para el estado local del componente. Son la primitiva reactiva oficial de Angular desde la 17 y simplifican mucho el código de UI.
- **Reactive Forms** para el formulario tipado.
- **Fetch + `ReadableStream`** para consumir el endpoint de streaming. No usamos `HttpClient` porque Angular aún no expone una API nativa cómoda para NDJSON token-a-token.

### 3.3 Modelo TypeScript (`src/app/models/estimation.ts`)

Espejo exacto de los tipos del backend, con sus enums representados como *string literal unions*:

```ts
export type ProjectType = 'mobile_app' | 'web_saas' | 'internal_tool' | 'data_pipeline';
export type DetailLevel = 'summary' | 'medium' | 'detailed';
export type OutputFormat = 'phases_table' | 'line_items' | 'narrative';
```

Junto con los tipos se exportan tres arrays (`PROJECT_TYPES`, `DETAIL_LEVELS`, `OUTPUT_FORMATS`) con el `value` técnico y la `label` en español que verá el usuario. Esto separa el dato que viaja al backend (en inglés, valor del enum) del texto visible en la interfaz (en español, traducible).

### 3.4 Servicio de streaming (`src/app/services/estimation.service.ts`)

Es la pieza más densa de la parte cliente. Convierte el stream NDJSON crudo del backend en una secuencia de eventos tipados (`token`, `metrics`, `error`, `done`) que el componente puede consumir con un `for await`.

Resumen del flujo:

1. `fetch('/api/v1/estimate/stream', …)` lanza la petición POST con el JSON del formulario.
2. Si la respuesta no es 2xx, emite un evento `error` y termina.
3. Obtiene el `ReadableStream` del cuerpo y lo lee con un `reader.read()` en bucle.
4. Cada *chunk* binario se decodifica con `TextDecoder` y se acumula en un `buffer` de texto. El buffer es necesario porque un chunk de red **no** corresponde a una línea JSON: puede traer media línea, una línea entera o tres líneas y media.
5. Mientras haya `\n` en el buffer, se parte por la primera ocurrencia, se parsea esa línea como JSON y se emite el evento correspondiente.
6. Al final del stream se vacía el resto del buffer.

Es un patrón clásico de *line-buffered parsing*. Es lo mismo que hace `iter_lines()` de `httpx` o el `for line in stream` de `requests`, pero implementado a mano porque el navegador no lo trae.

**Por qué un async generator.** Devuelve `AsyncGenerator<StreamEvent>` y eso permite al componente escribir:

```ts
for await (const event of this.api.stream(payload)) {
  if (event.type === 'token') this.output.update(p => p + event.text);
  …
}
```

Sin RxJS, sin observables, sin suscripciones que cancelar. El control de flujo es lineal y se lee como código síncrono.

### 3.5 Componente raíz (`src/app/app.component.ts` / `.html` / `.scss`)

Una sola pantalla con dos paneles:

- **Panel izquierdo — Formulario.** Tres selects (tipo de proyecto, nivel de detalle, formato de salida) y un textarea para la descripción. Validaciones de longitud mínima (20 caracteres) y máxima (2000) idénticas a las del backend, para fallar rápido sin necesidad de ir al servidor. Debajo, una tarjeta de métricas que aparece cuando el stream termina (proveedor, modelo, tokens de entrada/salida, tiempo de respuesta).
- **Panel derecho — Estimación.** Renderiza el texto que va llegando token a token dentro de un `<pre>`. Muestra estados visibles ("Esperando entrada", "En streaming…", "Generada") y un cuadro de error si el backend devuelve un fallo.

El estado del componente está en cuatro signals:

```ts
readonly streaming = signal(false);
readonly output = signal('');
readonly errorMessage = signal<string | null>(null);
readonly metrics = signal<StreamMetrics | null>(null);
```

Y `ChangeDetectionStrategy.OnPush` para que Angular solo recalcule la vista cuando los signals cambian. En streaming, donde se actualiza el texto muchas veces por segundo, esto importa.

### 3.6 Proxy de desarrollo (`proxy.conf.json` y `proxy.conf.docker.json`)

Angular sirve la app en `http://localhost:4200` y el backend está en `http://localhost:8000`. Sin nada más, las peticiones a `/api/...` del navegador irían contra `:4200` y fallarían (404 en dev, problema CORS en prod).

Solución: el dev server de Angular tiene una opción `proxyConfig`. Le decimos "todo lo que empiece por `/api` redirígelo a tal host". Hay dos ficheros:

- `proxy.conf.json` — Cuando se ejecuta `npm start` directamente en la máquina. Apunta a `http://localhost:8000`.
- `proxy.conf.docker.json` — Cuando el frontend corre en un contenedor Docker y el backend está fuera. Apunta a `http://host.docker.internal:8000`, que es el alias estándar para "la máquina anfitriona desde dentro de un contenedor".

### 3.7 Tests (`src/app/app.component.spec.ts`)

El scaffold de Angular genera un spec por componente. Lo hemos adaptado para:

- Verificar que el componente se instancia.
- Verificar que el toolbar renderiza el título "Estimador".
- Verificar que el formulario arranca inválido (porque la descripción es requerida).

Se usan `provideNoopAnimations()` en el `TestBed` para que Material Animations no rompa los tests sin un navegador real.

---

## 4. Configuración Docker — dos stacks independientes

La regla de diseño aquí: **cada proyecto tiene su propio `docker-compose.yml`** y se puede levantar/parar sin tocar el otro. No hay un compose "maestro" que sepa de ambos.

### 4.1 `estimator/docker-compose.yml` (backend)

- Construye la imagen Python (multi-stage con `uv`), publica en `:8000`, lee `.env`, monta `./app` para hot reload con `uvicorn --reload`.
- `healthcheck` apunta a `/health` con la stdlib de Python (la imagen `slim` no tiene `curl`).

### 4.2 `estimator-frontend/docker-compose.yml` (frontend)

- Construye la imagen Node 20 alpine.
- Publica el dev server en `:4200`.
- Monta `src/`, `public/`, `angular.json`, los `tsconfig.*.json` y `proxy.conf.docker.json` para que cualquier edición en local recargue el navegador automáticamente.
- Usa un **volumen anónimo** en `/app/node_modules`. Esto evita que un `node_modules` del host (o su ausencia) tape el del contenedor. Solución estándar para evitar mezclar binarios nativos entre macOS, Linux y Windows.
- `extra_hosts: ["host.docker.internal:host-gateway"]` para que en Linux el alias `host.docker.internal` resuelva al gateway de la red Docker. En macOS y Windows ya existe nativamente, pero esto no estorba.

### 4.3 Modos de uso

Hay tres formas válidas de trabajar:

1. **Todo en local sin Docker.** `uvicorn` y `npm start` en dos terminales. Es lo más rápido para iterar.
2. **Backend en Docker, frontend en local.** Se levanta `estimator/docker compose up` y se arranca `npm start` en local. El proxy apunta a `localhost:8000` (que sigue siendo el contenedor publicado en ese puerto).
3. **Ambos en Docker.** Se levantan los dos compose por separado. El frontend usa `proxy.conf.docker.json` y alcanza al backend a través de `host.docker.internal:8000`.

---

## 5. Cómo levantar todo

### Local sin Docker

```bash
# Terminal A — backend
cd estimator
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal B — frontend
cd estimator-frontend
npm install   # solo la primera vez
npm start     # http://localhost:4200
```

### Con Docker

```bash
# Backend
cd estimator
docker compose up --build

# Frontend (otra terminal)
cd estimator-frontend
docker compose up --build
```

### Ejecutar tests

```bash
# Backend (10 tests, milisegundos)
cd estimator
uv run pytest -q

# Frontend (Karma + Jasmine)
cd estimator-frontend
npm test
```

---

## 6. Trabajo futuro previsto para el directo

Tres puntos quedan deliberadamente fuera de este ejercicio y se tratarán en la sesión 04 en vivo:

1. **Forzar salida JSON estructurada del LLM** en lugar de texto libre. Hoy la respuesta sigue siendo Markdown.
2. **Validación del output con guardrails** — verificar que el JSON cumple un esquema y reintentar / corregir si no.
3. **Caching semántico** de respuestas — reutilizar estimaciones para descripciones equivalentes pero no idénticas, encima del cache *exact-match* que ya hay.

También quedan pendientes (bonus opcional del enunciado):

- Crear un `v2/` del prompt y probar `?prompt_version=v2` en producción.
- Añadir un campo opcional `reference_projects` al schema para inyectar proyectos similares vía `{% for %}` en la plantilla.
- Logging del prompt renderizado con `structlog`, emitiendo versión y hash.

---

## 7. Resumen rápido del valor añadido

- **Para el negocio.** El formulario acotado elimina la variabilidad por mala redacción del usuario y, al exponer parámetros explícitos (tipo de proyecto, detalle, formato), permite controlar la calidad del output sin pedir al usuario que "escriba mejor".
- **Para producto.** Versionar prompts en disco abre la puerta a iterar en el prompt como en el código: PR, revisión, test, despliegue, rollback. Ya no es un cambio de string en producción.
- **Para ingeniería.** El servicio LLM queda como una pieza pequeña y testeable. Las plantillas se cubren con tests en milisegundos. La interfaz Angular es la base sobre la que se montarán las siguientes pantallas del producto.
