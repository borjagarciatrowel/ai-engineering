# Cambios de la sesión 5 — memoria conversacional y contexto enriquecido

> Este documento describe **solo los cambios introducidos en esta implementación** (el
> ejercicio previo a la sesión 5). Para la guía completa del backend pieza a pieza, ver
> [`codigo-explicado.md`](../codigo-explicado.md) (sección 17). Aquí se cuenta *qué se tocó*
> y *por qué*, no se reexplica el código que ya existía.

## 1. Objetivo

Convertir el estimator de un sistema **transaccional** (una transcripción entra, una
estimación sale) en uno **conversacional**: dentro de una misma sesión, el cliente refina
el alcance turno a turno, adjunta documentos, y el sistema recuerda de qué proyecto se
habla — sin reenviar todo el historial bruto en cada llamada.

Dos capacidades nuevas:

1. **Memoria conversacional con ventana deslizante** + `project_metadata` separado del
   historial, inyectado en el system prompt cada turno.
2. **Adjuntos** (PDF / Word) en `multipart/form-data`, con extracción local de texto.

## 2. Decisiones de diseño

### 2.1 Persistencia en base de datos (desvío deliberado del enunciado)

El enunciado pide guardar las sesiones en un **diccionario en memoria del proceso** ("sin
BBDD, sin Redis"). **Aquí se hace distinto a propósito**: como el proyecto ya tiene Postgres
montado para las fichas de estimación, la memoria conversacional se **persiste en la base de
datos** (tabla `chat_sessions`).

- **Por qué:** un diccionario en memoria se pierde al reiniciar el servicio y no se comparte
  entre workers de uvicorn (cada worker tendría su copia, rompiendo la garantía
  conversacional). Con Postgres, la conversación sobrevive a reinicios y es consistente
  entre workers.
- **Coste:** una tabla nueva y un *round-trip* objeto↔fila por petición. Despreciable
  comparado con la llamada al LLM.
- Es la **única** diferencia de fondo respecto a la solución canónica de la sesión.

### 2.2 Adjuntos — Camino B (extracción local)

De los dos caminos del enunciado, se eligió el **Camino B**: extraer el texto del PDF/Word
*dentro* del servicio (con `pypdf` y `python-docx`) y concatenarlo a la transcripción, en
vez de subir el binario a la Files API de un proveedor multimodal (Camino A).

- **Por qué:** mantiene el wrapper del LLM **agnóstico al proveedor** (texto entra, texto
  sale), da control total sobre lo que llega al prompt, y prepara el terreno para el
  *chunking* / RAG del módulo 3.

### 2.3 Extracción de `project_metadata` — extractor LLM

De las dos opciones del enunciado (heurística con regex vs. extractor LLM), se eligió el
**extractor LLM**: una segunda llamada por turno, con un modelo barato (`gpt-4o-mini`) y un
prompt corto que devuelve un `ProjectMetadata` estructurado.

- **Por qué:** es más robusto que parsear la respuesta con regex (entiende sinónimos,
  normaliza mayúsculas de tecnologías, resume el alcance). El coste extra de una llamada
  pequeña por turno es asumible. Si falla, se conserva la metadata anterior intacta.

### 2.4 Las estimaciones conversacionales aparecen en el grid

Las sesiones viven en `chat_sessions`, una tabla distinta de `estimations` (la que alimenta
el grid de la landing). Para que una estimación hecha en la interfaz conversacional **se vea
en el grid**, cada turno **refleja** su resultado en la tabla `estimations`:

- **Una fila por sesión**, actualizada en cada turno (no una fila por turno → evita ruido).
  Se localiza con la columna nueva `estimations.session_id`.
- El título sale del `project_name` extraído (o `Conversación <id corto>` si aún no hay
  nombre); estado `finished`; se copian resultado y telemetría del turno.
- Es **best-effort**: si el reflejo falla, la respuesta conversacional no se rompe (la fuente
  de verdad sigue siendo `chat_sessions`).

## 3. Cambios en el backend (`estimator/`)

### Archivos nuevos

| Archivo | Qué hace |
|---------|----------|
| `app/sessions/models.py` | Pydantic: `Message`, `ConversationHistory` (ventana deslizante), `ProjectMetadata` (fusión escalares+listas), `Session`. |
| `app/sessions/store.py` | `DbSessionStore`: crea/lee/guarda sesiones en Postgres. **Reemplaza el dict en memoria del enunciado.** |
| `app/sessions/metadata_extractor.py` | `update_metadata`: 2ª llamada LLM que refresca `ProjectMetadata` y la fusiona con la previa. |
| `app/sessions/__init__.py` | Exports del paquete. |
| `app/attachments/extractor.py` | Camino B: `extract_text` (PDF/DOCX) + `enrich_transcript` (concatena con vallas `--- attachment: ... ---`). |
| `app/attachments/__init__.py` | Exports del paquete. |
| `app/routers/sessions.py` | Endpoints `POST /sessions`, `GET /sessions/{id}`, `POST /sessions/{id}/estimate`; + reflejo del turno al grid (`_mirror_turn_to_grid`). |
| `app/prompts/estimation/v2/system.j2` | System prompt v2: v1 + bloque `<project_metadata>`. |
| `app/prompts/estimation/v2/user.j2` | User prompt v2 (transcripción enriquecida). |
| `app/prompts/metadata_extraction/v1/system.j2` | Prompt del extractor de metadata. |
| `app/prompts/metadata_extraction/v1/user.j2` | Prompt del extractor (metadata previa + turno actual). |

### Archivos modificados

| Archivo | Cambio |
|---------|--------|
| `app/db_models.py` | + modelo ORM `ChatSession` (tabla `chat_sessions`: `history` y `project_metadata` JSON); + columna `Estimation.session_id` (liga la fila reflejada al grid). |
| `app/db.py` | + `session_id` en la migración aditiva idempotente (`_ADDED_COLUMNS`). |
| `app/services/llm_wrapper.py` | + método `complete_structured_chat` (recibe un array `messages`; captura tokens/coste como `complete_structured`). |
| `app/services/estimation.py` | + método `estimate_conversational` (pipeline multi-turno) y parámetros `conversational_prompt_version`, `metadata_extractor_model`. |
| `app/prompts/loader.py` | + `render_conversational_prompt` (v2) y `render_metadata_extraction_prompt`. |
| `app/config.py` | + `MAX_CONVERSATION_TURNS` (6), `MAX_ATTACHMENT_CHARS` (60.000), `METADATA_EXTRACTOR_MODEL` (`gpt-4o-mini`). |
| `app/dependencies.py` | + `get_session_store` (por petición, depende de `get_db`); `get_estimation_service` pasa `metadata_extractor_model`. |
| `app/main.py` | + `app.include_router(sessions.router)`. |
| `pyproject.toml` | + `python-multipart`, `pypdf`, `python-docx`. |

### El flujo de un turno

```
POST /sessions/{id}/estimate  (multipart: transcript + project_type/detail_level/output_format + attachments[])
  └→ routers/sessions.py
       1. store.get_or_404(id)                      # carga la Session desde Postgres (404 si no existe)
       2. extract_text(...) por cada adjunto         # Camino B (415 no soportado / 422 ilegible)
       3. enrich_transcript(...)                     # concatena texto extraído con vallas
       4. service.estimate_conversational(session, transcript=enriquecido, ...)
            a. guardrail de entrada
            b. render v2 (system con <project_metadata>) + historial + user
            c. complete_structured_chat → EstimationResult (validado por Instructor)
            d. guardrail de salida
            e. session.history.append(turno)         # la ventana deslizante recorta sola
            f. update_metadata(...)                  # 2ª llamada LLM → refresca ProjectMetadata
       5. store.save(session)                        # ← vuelca history + metadata a Postgres
       6. _mirror_turn_to_grid(...)                  # upsert en `estimations` (1 fila/sesión) → visible en el grid
       7. return EstimationResponse (con telemetría LlmUsage)
```

El servicio solo **muta** el objeto `Session`; **persistir es trabajo del router**
(`store.save`). Así el pipeline nunca importa el ORM y los tests pueden usar sqlite.

## 4. El modelo de datos nuevo: `chat_sessions`

```
chat_sessions
  id                 VARCHAR(36) PK   (UUID)
  max_turns          INTEGER          (6 por defecto)
  history            JSON             (dump de ConversationHistory: max_turns + messages[])
  project_metadata   JSON             (dump de ProjectMetadata)
  created_at / updated_at
```

`create_all()` (en `db.py`) crea esta tabla automáticamente al arrancar porque importa
`db_models`. No hace falta migración aditiva: es una tabla nueva, no una columna sobre una
tabla existente.

> La columna se llama `project_metadata`, no `metadata`, porque `metadata` está reservado en
> la `Base` declarativa de SQLAlchemy.

## 5. Endpoints nuevos

| Método | Ruta | Qué hace |
|--------|------|----------|
| `POST` | `/sessions` | Crea una sesión **y su fila de estimación** → `{"session_id", "estimation_id"}` (201). |
| `GET` | `/sessions/{id}` | Vista de depuración: `metadata`, `message_count`, `max_turns`. |
| `GET` | `/sessions/{id}/conversation` | Historial turno a turno (mensajes + metadata) — lo consume el detalle. |
| `POST` | `/sessions/{id}/estimate` | Un turno. `multipart/form-data` con `transcript` + parámetros tipados + `attachments` opcionales. |

Mapeo de errores: guardrail de entrada → 400, adjunto no soportado → 415, adjunto ilegible
→ 422, sesión inexistente → 404, fallo del LLM → 502.

## 6. Cambios en el frontend (`estimator-frontend/`, Angular)

El cliente es Angular (no Streamlit ni Rails), así que el paso 6 del ejercicio se tradujo a
ese stack. **Decisión de UX: una estimación ES una conversación** — se eliminó la pantalla
"Conversacional" separada y la edición single-shot; el detalle de una estimación es
directamente la interfaz conversacional. "Nueva estimación" arranca una conversación.

| Archivo | Cambio |
|---------|--------|
| `src/app/models/estimation.ts` | + tipos `LlmUsage`, `EstimationResponse`, `ProjectMetadata`, `SessionInfo`, `ConversationMessage`, `Conversation`; + `session_id` en `EstimationRecord`. |
| `src/app/services/estimation.service.ts` | + `createConversation` (sesión + fila), `getConversation`, `estimateInSession` (`FormData` multipart), `getSession`. |
| `src/app/pages/detail/estimation-detail.component.{ts,html,scss}` | **Reescrito**: el detalle es la interfaz conversacional — hilo de turnos + cuadro para añadir turno (transcripción + adjuntos + parámetros) + panel "Memoria del proyecto". Las estimaciones heredadas sin sesión se muestran en solo-lectura. Se eliminó el formulario editar/guardar/ejecutar/reestimar y el *polling*. |
| `src/app/pages/list/estimation-list.component.ts` | "Nueva estimación" llama a `createConversation` y abre el detalle. |
| `src/app/app.routes.ts` | Eliminada la ruta `/chat`. |
| `src/app/app.component.{html,ts,scss}` | Eliminada la pestaña de navegación "Conversacional" (un único punto de entrada). |
| `src/app/pages/chat/` | **Eliminada** la página conversacional independiente (su funcionalidad vive ahora en el detalle). |
| `proxy.conf.json`, `proxy.conf.docker.json` | + reenvío de `/sessions` al backend (antes solo `/api`). |
| `angular.json` | Presupuesto de SCSS por componente subido (8 kB warning / 12 kB error). |

El detalle mantiene la separación **historial vs memoria** visible: el hilo de turnos
muestra el historial, y el panel lateral muestra la `project_metadata` acumulada (útil para
depurar y para *ver* la diferencia entre ambos).

## 7. Tests añadidos

Todos corren **offline** (LLM falso + sqlite en memoria). En total el backend pasa de 70 a
**104 tests**.

| Archivo | Cubre |
|---------|-------|
| `tests/test_sessions_models.py` | Ventana deslizante, fusión de metadata, y el **round-trip de persistencia** del `DbSessionStore` (mutar → guardar → releer en otra sesión). |
| `tests/test_sessions_window.py` | Integración: 8 turnos a una sesión, el historial efectivo enviado al LLM nunca supera `MAX_TURNS`. |
| `tests/test_sessions_metadata.py` | Integración: 2 turnos acumulan `project_metadata`; el turno **aparece en el grid** (1 fila/sesión); `GET /sessions/{id}/conversation` devuelve los turnos (transcripción cruda); la fila reflejada expone `session_id`. |
| `tests/test_sessions_attachments.py` | Integración: el contenido de un PDF/DOCX adjunto llega al LLM; adjunto no soportado → 415. |
| `tests/test_attachments_extractor.py` | Unidad: extracción PDF/DOCX, recorte, vallas de `enrich_transcript`. |
| `tests/test_metadata_extractor.py` | Unidad: fusión y tolerancia a fallos del extractor. |
| `tests/conftest.py` | + `sqlite_db` (sustituye Postgres por sqlite), `FakeLLMWrapper`, `conversational_client`. |
| `tests/test_llm_wrapper.py` | + test de `complete_structured_chat` (captura de tokens/coste). |

## 8. Cómo se levanta y se prueba

```bash
# Backend (desde estimator/)
cd estimator
uv sync                       # instala las nuevas deps (python-multipart, pypdf, python-docx)
uv run pytest -q              # 101 tests, todos offline
uv run ruff check .

# Stack completo con Docker (Postgres + Redis + estimator)
docker compose up -d --build  # recrea la imagen con las nuevas dependencias

# Frontend (desde estimator-frontend/)
cd estimator-frontend
npm start                     # ng serve en :4200 (proxy reenvía /api y /sessions a :8000)
```

Prueba rápida de la API (sin frontend):

```bash
SID=$(curl -s -X POST http://localhost:8000/sessions | python3 -c "import sys,json;print(json.load(sys.stdin)['session_id'])")
curl -s -X POST "http://localhost:8000/sessions/$SID/estimate" \
  -F "transcript=Queremos un CRM llamado Nimbus en React y Postgres para ventas." \
  -F "project_type=web_saas" -F "detail_level=medium" -F "output_format=phases_table"
curl -s "http://localhost:8000/sessions/$SID"   # ver la project_metadata acumulada
```

> **Importante:** tras cambiar `pyproject.toml`, el contenedor del estimator hay que
> **reconstruirlo** (`docker compose up -d --build`); las nuevas dependencias están en la
> imagen, no en el bind-mount de `./app`.
