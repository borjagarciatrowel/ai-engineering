# Sesión 14 — Sistemas multi-agente: supervisor, comunicación, HITL, competición y privilegio (versión clara)

> Versión simplificada del resumen de los 6 artículos de la Sesión 14.
> Misma información, menos paja. Cada término técnico se explica en una frase.
> **Hilo conductor:** la Sesión 13 dejó un grafo que funciona — estado tipado, nodos, checkpointer sobre Postgres, trazas limpias. La Sesión 14 se pregunta qué justifica convertirlo en un *sistema multi-agente*, y la respuesta no es "más nodos con nombres más ambiciosos". La frontera real es **quién es dueño del control flow**: mientras el orden lo fija el código, tienes un workflow; cuando lo decide el modelo en runtime, tienes un sistema agéntico. A partir de ahí, cuatro preguntas concretas ordenan toda la sesión: **quién enruta** (supervisor), **cómo se hablan los agentes** (estado compartido / handoff / mensajes), **cuándo el sistema no debe decidir solo** (human-in-the-loop sobre el checkpointer) y **qué puede tocar cada agente** (mínimo privilegio, validación y auditoría). Más un quinto tema transversal: cuándo merece la pena que dos agentes **compitan** en lugar de cooperar.

---

## Glosario base (léelo una vez y vuelve cuando haga falta)

| Término | Qué es, en una frase |
|---|---|
| **Workflow vs sistema agéntico** | En el workflow el orden lo fija el código; en el agéntico lo decide el modelo en runtime. La diferencia no es el número de nodos. |
| **Supervisor** | Nodo que en cada vuelta mira el estado y decide qué especialista actúa; no hace trabajo de dominio, solo enruta. |
| **`Command`** | Objeto de LangGraph que hace dos cosas a la vez: actualiza el estado (`update=`) y mueve el control (`goto=`). |
| **`Command[AgentName]`** | El tipo de retorno tipado: LangGraph lo usa para inferir los destinos posibles al construir el grafo. El `Literal` de destinos y el que devuelve el modelo son **el mismo**. |
| **Digest de estado** | Proyección compacta del estado (5 líneas) que ve el supervisor para decidir, en lugar del historial completo de mensajes. Coste constante por decisión. |
| **`routing_steps` / `MAX_ROUTING_STEPS`** | El contador y su techo: el freno que impide que un supervisor confundido rebote entre agentes hasta agotar la cuenta. |
| **`routing_trail`** | Campo acumulador con cada decisión de enrutado (`next_agent` + `reason`): la memoria de por qué el sistema fue donde fue. |
| **Supervisor híbrido** | Enrutador que resuelve por reglas lo que es determinista (precondiciones) y solo llama al modelo cuando hay ambigüedad real. |
| **Plano vs jerárquico** | Un supervisor con N especialistas (empieza aquí) frente a equipos con sub-supervisores (llega aquí cuando el plano falla con ~15 opciones). |
| **Blackboard (estado compartido)** | Patrón de los años 70: nadie habla con nadie, todos escriben en una pizarra común. Es lo que ya tienes con `EstimationState`. |
| **Reducer** | La política de qué pasa cuando dos agentes escriben la misma clave: sobrescribir (por defecto) o acumular (`operator.add`). |
| **Handoff / swarm** | El agente que termina elige él mismo quién sigue y le pasa el testigo, sin volver al centro. En LangGraph, una tool que devuelve un `Command`. |
| **`graph=Command.PARENT`** | Lo que hace que el `goto` escape del subgrafo del agente y aterrice en el grafo padre. Olvidarlo es el error nº 1 del handoff a mano. |
| **`task_brief`** | Lo que viaja en el testigo de un handoff: ni todo el historial (caro) ni nada (ciego). Decisión explícita, sin respuesta universal. |
| **Mensajes / event bus** | Un agente publica un evento; quién lo consuma no es asunto suyo. Arquitectura orientada a eventos aplicada a agentes. |
| **`interrupt()`** | Lanza una excepción de control: LangGraph escribe el estado en el checkpoint, la ejecución termina y el proceso queda libre. No es un `sleep`. |
| **`Command(resume=...)`** | La reanudación: el mismo `ainvoke`, con el `thread_id` de siempre, continuando desde el checkpoint. No hay API especial. |
| **Competición + síntesis** | Dos agentes atacan la MISMA tarea con criterios opuestos y un tercero decide qué hacer con el desacuerdo. |
| **Divergencia** | `(max − min) / max` entre las propuestas. Es aritmética, no juicio: se calcula en código, jamás se le pide a un LLM. |
| **Mínimo privilegio** | Cada agente recibe solo las tools que su función necesita. Lo que no está en su mano no puede usarlo mal. |
| **`ToolRisk`** | Clasificación explícita de cada tool: `PURE` (sin efectos) / `READ` / `WRITE` / `EXTERNAL` (actúa sobre el mundo). |
| **Action guard** | Código plano y determinista por el que pasa toda acción con efectos antes de ejecutarse: privilegio + validación de argumentos. |
| **Auditoría** | Registro de toda acción con efectos, **incluidas las denegadas**. Lo que no se registra, no ocurrió. |

---

## La idea en una página

Un sistema multi-agente, en la forma que sirve en producción, **es tu grafo reorganizado**: mismo estado tipado, mismos nodos-función, mismo checkpointer. Lo único que cambia es que hay un nodo que decide y unos nodos que solo ven sus propias herramientas. No hay paradigma nuevo; hay una capa pequeña sobre principios de ingeniería que ya aplicas.

| # | El tema | El artículo |
|---|---------|-------------|
| 1 | **¿Cuándo deja de ser "un grafo con más nodos"?** El techo del grafo único, cooperación frente a competición, y lo que cuesta de verdad multiplicar agentes. | **Cuándo un sistema multi-agente deja de ser un grafo con más nodos** (Parte 1) |
| 2 | **¿Quién decide qué se ejecuta ahora?** El supervisor construido a mano con `StateGraph` y `Command`, con digest, decisión tipada, presupuesto de enrutado y traza. | **El supervisor: enrutado a mano** (Parte 2) |
| 3 | **¿Cómo se pasan información los agentes?** Tres patrones —estado compartido, handoff directo, mensajes— que son tres puntos de una escalera, no tres alternativas del mismo nivel. | **Patrones de comunicación entre agentes** (Parte 3) |
| 4 | **¿Y cuando el sistema no debe decidir solo?** `interrupt()` sobre el checkpointer que ya tienes, y el contrato de esa pausa entre las tres capas. | **Human-in-the-loop: interrupt, pausa y reanudación** (Parte 4) |
| 5 | **¿Cuánto te puedes fiar del número?** Dos estimadores con criterios opuestos, divergencia calculada en código y un sintetizador que no promedia. | **Competición y síntesis entre agentes** (Parte 5) |
| 6 | **¿Qué puede tocar cada agente?** Tres capas de contención —privilegio, validación de acción, auditoría— y ninguna vive en el prompt. | **Mínimo privilegio, validación y auditoría** (Parte 6) |

> **El hilo que atraviesa las seis partes:** cada pieza resulta ser un principio de ingeniería conocido aplicado a un componente que a veces alucina — separación de responsabilidades, contratos entre capas, **no confíes en el cliente** (aquí el cliente es el modelo), persistencia para sobrevivir a fallos, defensa en profundidad. La capa genuinamente nueva es pequeña. Y el criterio se repite en las seis: **no subas un escalón hasta que el anterior te falle de forma medida, no imaginada.**

---

# Parte 1 — Cuándo un sistema multi-agente deja de ser "un grafo con más nodos"

## El techo del grafo único

Un grafo dirigido con nodos-función fija el *control flow* en el código: tú decides, en tiempo de escritura, que después de extraer requisitos se clasifican componentes. Las aristas condicionales dan flexibilidad, pero acotada: son ramas que alguien previó y escribió. **El modelo rellena huecos; no elige el camino.** Eso es una ventaja enorme — determinista, predecible, barato de trazar, fácil de testear. Si el proceso de negocio tiene una secuencia estable (y estimar software, en su forma canónica, la tiene), el grafo lineal **es la respuesta correcta**. Empezar por multi-agente con flujo fijo es montar microservicios para un CRUD de tres tablas: no está mal por complejo, está mal porque la complejidad no compra nada.

## Las cuatro señales de que has golpeado el techo

1. **El prompt de un nodo acumula reglas de dominios distintos.** El nodo que genera la estimación sabe calcular horas *y* interpretar presupuestos históricos *y* ajustar por seniority *y* reaccionar a un ERP legacy. Ya no es un paso: es un agente sobrecargado con cuatro responsabilidades peleándose en una ventana de contexto. Síntoma clásico: tocas una regla para arreglar un caso y rompes otro sin relación. Es acoplamiento, el mismo de una clase de 800 líneas.
2. **El conjunto de tools crece en un único espacio de decisión.** Con seis, ocho, doce tools en un solo nodo, la tasa de elección incorrecta sube con el número de opciones. Repartirlas entre agentes con menos opciones cada uno no es solo higiene de seguridad: **mejora la precisión**.
3. **El orden deja de ser conocido de antemano.** Es la señal definitiva. Tres módulos independientes —un CRUD conocido, una integración sin precedente, una migración— tienen caminos óptimos distintos. Codificarlos como aristas condicionales convierte el grafo en un árbol de decisión escrito a mano que envejece mal. **Cuando quien decide qué se ejecuta a continuación deja de ser el código y pasa a ser el modelo, has cruzado la frontera.**
4. **Las responsabilidades evolucionan a ritmos distintos.** Si el equipo de datos itera semanalmente sobre la búsqueda de presupuestos y negocio toca validación una vez al trimestre, tenerlos en el mismo nodo es un problema organizativo antes que técnico. Ejes de cambio distintos piden componentes distintos.

## Cooperar o competir: la segunda decisión

Cuando la decisión de ir a multi-agente está justificada, queda una segunda que la gente se salta y que determina coste y comportamiento:

- **Cooperación (por defecto).** Cada agente aporta una pieza distinta y el resultado es la composición: extractor → buscador → generador → validador. Tiene sentido porque **las contribuciones son ortogonales**: extraer requisitos y validar coherencia no compiten, se necesitan. Coste: una pasada por el flujo. Riesgo: el clásico de las cadenas — un eslabón débil contamina todo lo que viene detrás, y nadie aguas abajo tiene forma de saberlo.
- **Competición.** Dos o más agentes atacan **la misma tarea** con criterios distintos y un tercero sintetiza. Lo valioso no es que el sintetizador "elija la buena": es que **la divergencia entre propuestas es información que no tenías**. 340h vs 190h dice incertidumbre estructural; 250 vs 270 dice caso predecible. Con un estimador único obtienes un número y no sabes cuánto fiarte.

> **Regla de bolsillo:** cooperación para *descomponer trabajo*; competición para *atacar incertidumbre*. No las mezcles por defecto: la competición aplicada a todo multiplica la factura sin multiplicar la calidad.

## Lo que te va a costar

- **Coste y latencia.** Cada salto de enrutado es una llamada al modelo que no produce trabajo útil: solo decide. Con supervisor central, una tarea que toque dos especialistas son cuatro llamadas donde el grafo lineal hacía dos. Puede merecer la pena; lo que no puede es que lo descubras en la factura.
- **Pérdida de contexto en las transiciones.** ¿Qué se lleva el siguiente agente? Todo el historial → el contexto crece sin control. Solo un resumen → ese resumen es un cuello de botella semántico: lo que no esté ahí no existe para quien viene. No hay respuesta universal, y ninguna librería la toma bien por ti.
- **No-determinismo en el control flow.** Dos ejecuciones sobre la misma transcripción pueden recorrer caminos distintos. Complica tests, reproducción de bugs y explicaciones al cliente. Es gestionable (trazas, checkpoints, temperatura baja en el enrutado, tests sobre el resultado y no sobre el camino) pero es un **impuesto permanente**.
- **Superficie de fallo mayor.** Cinco agentes son cinco sitios donde alucinar, cinco conjuntos de tools que invocar mal y un enrutador que puede quedarse en bucle. El grafo lineal, con toda su rigidez, tenía una propiedad valiosa: si fallaba, sabías exactamente dónde.
- **El coste cognitivo.** El siguiente desarrollador tiene que entender cinco prompts, un protocolo de enrutado y una pizarra compartida, en lugar de leer cinco funciones en orden.

## Cuándo *no* hacerlo

- **Si el flujo es fijo, no necesitas supervisor.** Uno cuya única política es "primero A, luego B, luego C" es una arista condicional cara, con una llamada de más y aleatoriedad gratis.
- **Si el problema real es un prompt malo, arregla el prompt.** Repartir un prompt mediocre entre cuatro agentes deja cuatro prompts mediocres y un problema de coordinación encima.
- **Si no tienes observabilidad, no añadas agentes.** Un multi-agente sin trazas por nodo no es un sistema: es una caja negra con opiniones. La instrumentación es **precondición**, no extra.

---

# Parte 2 — El supervisor: construir el enrutado a mano con `StateGraph` y `Command`

## Qué hace exactamente un supervisor

Tres cosas, y conviene separarlas porque la literatura las mezcla: **descomponer** (qué piezas de trabajo faltan), **delegar** (elegir el especialista y darle el control) y **consolidar** (cerrar cuando no falta nada). Lo que **no** hace, si está bien diseñado: trabajo de dominio. No estima horas, no lee presupuestos, no valida coherencia. **Si tiene tools de negocio en la mano, deja de llamarlo supervisor**: es un agente más que además enruta, y has reintroducido el nodo sobrecargado que querías eliminar. Un supervisor bien hecho es un nodo **sin ninguna tool**; su única salida es una decisión.

## El estado, y el digest

Lo primero que hay que decidir no es *cómo* enruta, sino **qué ve para enrutar**. La tentación —y el valor por defecto de varias abstracciones del ecosistema— es pasarle el historial completo de mensajes. Es mala idea en cuanto el flujo tiene más de dos saltos: el contexto crece sin control, el coste por decisión sube en cada iteración y la señal relevante queda enterrada.

El supervisor no necesita saber **qué dijo** el buscador de presupuestos. Necesita saber **si ya buscó**. Eso es un *digest*: una proyección compacta del estado, construida por ti, que responde a la única pregunta que el supervisor tiene que resolver.

```python
def build_state_digest(state: EstimationState) -> str:
    """Compact projection of the state. This is all the supervisor gets."""
    return (
        f"requirements_extracted: {len(state['requirements'])} items\n"
        f"budget_matches_found: {len(state['budget_matches'])}\n"
        f"estimate_produced: {state['estimate'] is not None}\n"
        f"validation_done: {state['validation'] is not None}\n"
        f"routing_steps_so_far: {state['routing_steps']}"
    )
```

Cinco líneas. **Coste constante por decisión**, independientemente de lo larga que sea la transcripción o de cuántas iteraciones lleve el flujo. Si más adelante el supervisor necesita más información, la añades al digest de forma explícita y sabes exactamente lo que estás pagando.

Al estado se le añaden dos campos que no son decorativos: `routing_steps: int` (el freno) y `routing_trail: Annotated[list[dict], operator.add]` (la memoria de lo que hizo).

## El enrutado como decisión tipada

Un supervisor cuyo output es texto libre es un bug esperando a ocurrir. La decisión tiene que ser un valor de un **conjunto cerrado**, validado, que rompa ruidosamente si el modelo se sale del guion.

```python
AgentName = Literal[
    "requirements_extractor", "budget_searcher",
    "estimate_generator", "coherence_validator", "finalize",
]

class SupervisorDecision(BaseModel):
    next_agent: AgentName
    reason: str  # nadie lo lee en runtime; lo lees TÚ en la traza, a las 3 de la mañana
```

El nodo, entonces, hace tres cosas que merecen atención:

- **`Command` hace dos cosas a la vez:** actualiza el estado (`update=`) y mueve el control (`goto=`). Es lo que permite que el enrutado sea una decisión **del nodo** y no una arista condicional declarada fuera. Y el tipo de retorno `Command[AgentName]` no es cosmético: LangGraph lo usa para inferir los destinos al construir el grafo, así que **el conjunto de destinos y el conjunto de valores que el modelo puede devolver son literalmente el mismo `Literal`**.
- **El presupuesto de enrutado es innegociable.** `MAX_ROUTING_STEPS` es lo único que impide que un supervisor confundido rebote entre dos agentes hasta agotar la cuenta. Un bucle infinito en un grafo determinista es un bug evidente; en un grafo enrutado por un modelo es **el comportamiento por defecto ante una instrucción ambigua**. Techo desde la primera línea, no después del primer susto.
- **El span lleva la decisión, no la respuesta.** `next_agent` y `reason` como atributos del span convierten la traza en un registro navegable de cada bifurcación. Esto es exactamente lo que se pierde cuando el enrutado ocurre dentro de una abstracción de librería, y es la razón principal para construirlo a mano.

## Los trabajadores devuelven el control

Cada especialista hace su trabajo, escribe su parcial en el estado y devuelve el testigo al supervisor. Nada más. `return Command(goto="supervisor", update={"budget_matches": matches})`. Fíjate en el reducer: si `budget_matches` está anotado con `operator.add`, el agente **acumula** en lugar de sobrescribir — y si el supervisor decide invocarlo dos veces (cosa que puede hacer, porque la ruta es suya), los resultados se suman en vez de pisarse. **La semántica de acumulación es una decisión de diseño del estado, no un accidente.**

## Montar el grafo: una sola arista declarada

```python
builder.add_edge(START, "supervisor")
graph = builder.compile(checkpointer=checkpointer)
```

Todas las demás transiciones viven dentro de los nodos, en los `Command`. Es intencionado: **el grafo ya no describe un flujo, describe un conjunto de capacidades y un enrutador.** La forma del recorrido emerge en ejecución. Y el checkpointer es el mismo de siempre sobre el mismo Postgres — sin infraestructura nueva —, lo que significa que cada estado intermedio del ciclo de enrutado queda persistido y la ejecución puede pararse, inspeccionarse y reanudarse en cualquiera de sus saltos.

## El impuesto de enrutado, y el supervisor híbrido

Cada decisión del supervisor es una llamada que no produce ni una hora de estimación. En topología plana, una tarea que toque cuatro especialistas cuesta **ocho** llamadas (cuatro de trabajo, cuatro de enrutado) donde el grafo lineal hacía cuatro: **100% de sobrecoste** por la flexibilidad de que la ruta se decida sola. Ese impuesto se justifica si la ruta *de verdad* varía; si en el 95% de los casos el supervisor elige la misma secuencia, estás pagando un modelo para que reinvente un `for` cada vez.

De ahí la postura que va contra la corriente del ecosistema: **la mayoría de las decisiones de enrutado no necesitan un LLM.** Que los requisitos deban extraerse antes de buscar presupuestos no es un juicio matizado: es una **precondición**. Codificarla como instrucción en un system prompt es cambiar una garantía por una probabilidad, y encima pagando.

```python
async def supervisor(state) -> Command[AgentName]:
    if state["routing_steps"] >= MAX_ROUTING_STEPS:
        return Command(goto="finalize", update={"status": "routing_budget_exhausted"})
    # Precondiciones deterministas: sin llamada al modelo.
    if not state["requirements"]:
        return Command(goto="requirements_extractor", update=_bump(state))
    if not state["budget_matches"]:
        return Command(goto="budget_searcher", update=_bump(state))
    # Ambigüedad real: aquí el modelo se gana el sueldo.
    return await route_with_model(state)
```

Más barato, más rápido, más predecible y más fácil de testear, **conservando la inteligencia exactamente donde aporta**. Tiene además una virtud pedagógica: te obliga a nombrar cuáles son las decisiones difíciles de tu dominio. Si al escribirlo descubres que no hay ninguna ambigüedad real, has descubierto algo importante — **no necesitas un supervisor con modelo; necesitas el grafo que ya tenías.**

## No-determinismo y testing

Cuando la ruta la decide un modelo, dos ejecuciones sobre la misma transcripción pueden recorrer caminos distintos. Consecuencia práctica: **no testees el camino, testea el resultado y las invariantes.** Que se haya producido una estimación. Que ningún agente actuara sin sus precondiciones. Que `routing_steps` no superara el techo. El `routing_trail` te da todo eso en un campo del estado, inspeccionable desde un test sin instrumentación adicional.

## Plano, jerárquico, y las abstracciones

Con cuatro especialistas, un supervisor plano va sobrado. El problema aparece con quince: el enrutador tiene que discriminar entre quince opciones en cada decisión y **su precisión se degrada exactamente igual que la de un agente con quince tools**. La respuesta es agrupar por equipos, con un supervisor de nivel superior y sub-supervisores. El coste es real: un nivel más de jerarquía es una llamada más de enrutado por salto y una traza más profunda. **No empieces aquí; llega aquí cuando el plano empiece a fallar.**

Sobre las abstracciones (`create_supervisor` y compañía): merece la pena saber que existen y saber esto otro — **la propia recomendación actual de LangChain para la mayoría de casos es implementar el patrón supervisor directamente**, con tools y `Command`, precisamente porque así conservas el control sobre qué contexto recibe cada agente y cada decisión de enrutado queda visible en las trazas. La regla general: *la abstracción que te oculta la decisión que necesitas inspeccionar no te está ahorrando trabajo, te lo está aplazando.*

---

# Parte 3 — Patrones de comunicación entre agentes

Hay una decisión en tu arquitectura multi-agente que probablemente no recuerdas haber tomado: **cómo se comunican los agentes entre sí**. No la recuerdas porque vino de regalo con el framework. Hay tres patrones, los tres legítimos, y el orden en que te los vas a encontrar en producción es exactamente el orden en que aparecen aquí.

## 1. Estado compartido: la pizarra que ya tienes

El patrón se llama **blackboard** y viene de la IA de los años setenta: un grupo de especialistas frente a una pizarra; ninguno habla con otro, cada uno mira lo escrito, ve si puede aportar algo y escribe su contribución. Tu `EstimationState` **es** la pizarra. El `budget_searcher` no le pasa nada al `estimate_generator`: escribe en `budget_matches` y se va. Están completamente desacoplados el uno del otro — **su único acoplamiento es al esquema del estado**. Y ese acoplamiento (al esquema, no entre componentes) es el mismo que ya gestionas entre servicios que comparten base de datos o entre un frontend y el contrato de una API. Añadir un agente no obliga a tocar ninguno existente: solo a añadir un campo.

**El detalle que sí importa: los reducers.** La pizarra tiene una única pregunta difícil — qué pasa cuando dos agentes escriben la misma clave. En un flujo estrictamente secuencial nunca ocurre. Pero en cuanto el supervisor lanza dos agentes en paralelo, tienes dos escrituras concurrentes y, sin política explícita, **la última gana y la primera desaparece en silencio**. La regla de diseño: *para cada campo del estado, decide conscientemente si acumula o sobrescribe.* Los campos que un solo agente produce una vez (`estimate`, `validation`) sobrescriben y está bien; los campos donde varios agentes o varias invocaciones aportan (`budget_matches`, `routing_trail`) acumulan. **Un campo que debería acumular pero sobrescribe es una pérdida silenciosa de datos**, y de los bugs más difíciles de ver: el sistema no falla, simplemente estima con menos evidencia de la que buscó.

**La otra cara.** Dos límites reales: (a) **el estado crece** — todo lo que un agente pueda necesitar tiene que estar en el esquema, y con seis agentes `EstimationState` empieza a parecerse a un objeto Dios del que cada agente usa el 15%; el mismo olor que un modelo ActiveRecord de cuarenta columnas, y la misma mitigación: **proyecciones**, cada agente recibe la vista que le corresponde; (b) **todo el mundo lo puede leer todo** — si un agente maneja información sensible y otro no debería verla, el estado compartido no te protege: eso deja de ser comunicación y pasa a ser privilegio (Parte 6).

**Cuándo usarlo: por defecto.** Ya lo tienes, es trazable, es barato y desacopla. No lo cambies hasta que algo te obligue.

## 2. Handoff directo: cuando el centro es el cuello de botella

En el patrón supervisor el control siempre vuelve al centro: agente → supervisor → agente → supervisor. Cada retorno es una llamada cuyo único producto es una decisión de enrutado. El **handoff** elimina ese viaje de vuelta: el agente que termina decide él mismo quién sigue y le pasa el testigo. En el ecosistema esto se conoce como *swarm*, y el mecanismo en LangGraph es una **tool que en lugar de devolver un dato devuelve un `Command`**.

```python
@tool(f"handoff_to_{target_agent}", description=description)
def handoff(task_brief: Annotated[str, "What the next agent must do..."],
            tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    return Command(
        goto=target_agent,
        graph=Command.PARENT,   # sin esto, el goto busca dentro del subgrafo y no lo encuentra
        update={"messages": [ToolMessage(...)], "task_brief": task_brief},
    )
```

Dos cosas que merecen entenderse bien:

- **`graph=Command.PARENT`** es lo que hace que el salto escape del subgrafo del agente y aterrice en el grafo padre. Sin eso, el `goto` buscaría un nodo dentro del propio agente. **Es el error número uno al implementar handoff a mano.**
- **`task_brief` es la decisión de diseño de verdad: ¿qué viaja en el testigo?** Historial completo → el siguiente hereda todo el contexto, todo el coste y todo el ruido. Solo un brief → contexto limpio pero cuello de botella semántico: **lo que no esté en el brief no existe para el que viene**. Un requisito que el buscador consideró irrelevante es un requisito que el estimador jamás verá. No hay respuesta universal; hay una decisión explícita, y **el valor por defecto de casi todas las librerías —pasar todo el historial— es el que peor escala**.

**Lo que ganas y lo que pagas.** Una tarea que toca dos especialistas: supervisor = 4 llamadas (enrutar, trabajar, enrutar, trabajar); handoff = 2, porque la decisión de enrutado viaja **dentro** de la llamada del agente, como una tool call más. A escala, eso es dinero y latencia. Lo que pagas es **acoplamiento topológico**: cada agente necesita conocer a sus vecinos y tener una tool por destino posible; añadir un agente obliga a decidir quién puede saltar hacia él y a tocar esos agentes. Has cambiado una estrella por una malla, y las mallas crecen mal. Y pagas en **trazabilidad**: con supervisor todas las decisiones están en un sitio (`routing_trail`); con handoff están repartidas y reconstruir el porqué exige recorrer los saltos.

**Cuándo usarlo:** cuando el enrutado central se haya convertido en el cuello de botella **medible** —de coste o de latencia— y las transiciones sean mayoritariamente locales y predecibles. No antes. *El handoff se gana su sitio; no se elige por elegancia.*

## 3. Mensajes: cuando los agentes dejan de compartir proceso

Los dos patrones anteriores comparten una premisa que nadie enuncia: **todos los agentes viven en el mismo proceso**. Comparten memoria, objeto de estado y traza; por eso `Command(goto=...)` funciona. El patrón de mensajes rompe esa premisa: un agente publica un evento (`estimation.requirements_extracted`) y a quién le llegue, y cuándo, no es asunto suyo. Nadie llama a nadie.

Esto debería sonarte, porque no es una idea de IA: es **arquitectura orientada a eventos**, la misma que llevas años aplicando entre servicios. Las propiedades son las que conoces (desacoplamiento máximo, escalado independiente por consumidor, reintentos y colas de fallidos, resiliencia) y los costes también: **consistencia eventual** (el estado ya no es una foto coherente en un objeto), **trazabilidad distribuida** (hace falta un `correlation_id` y una herramienta que sepa coserlo todo) y **complejidad operativa** (un bus es infraestructura que hay que desplegar, monitorizar y mantener).

**Cuándo usarlo:** cuando los agentes dejan de ser funciones de un servicio y pasan a ser **servicios** — ciclos de vida distintos, despliegue separado, otro equipo los escribe. Mientras vivan todos dentro del servicio IA, es infraestructura que complica sin comprar nada.

## La postura

Los tres no son alternativas del mismo nivel: son **tres puntos de una escalera**, y subir un escalón sin necesitarlo es la forma más común de arruinar una arquitectura multi-agente. Estado compartido por defecto (mejor ratio de trazabilidad por unidad de complejidad; la mayoría de sistemas se quedan aquí y hacen bien). Handoff cuando el impuesto de enrutado sea un problema medido, no imaginado. Mensajes cuando los agentes crucen la frontera del proceso — ahí ya no eliges un patrón de comunicación, eliges una arquitectura de sistemas distribuidos.

Y **son combinables**: un supervisor sobre estado compartido dentro del servicio IA, que publica un evento cuando la estimación está lista para que el backend de negocio reaccione, es perfectamente coherente. **La pregunta nunca es cuál es el mejor patrón, sino qué patrón corresponde a cada frontera del sistema.**

---

# Parte 4 — Human-in-the-loop: `interrupt`, pausa y reanudación sobre el checkpointer

## La pausa vive en el checkpointer

Tu sistema acaba de producir 840 horas para un CRUD de tres entidades cuando el histórico dice 120–200. Nadie va a mandar eso a un cliente. Lo interesante es que el sistema **sabía** que algo iba mal: el validador tenía delante el rango histórico. La pregunta no es cómo evitar que se equivoque, sino qué debe hacer **cuando detecta que no está en condiciones de responder solo**. La respuesta fácil es un `if` que devuelve error. La correcta es más incómoda: **detenerse, enseñárselo a una persona y esperar**.

Y esperar es lo difícil, porque la persona puede tardar diez minutos o tres días: tu proceso Python no puede quedarse bloqueado en un `input()`. La ejecución tiene que **morir y poder resucitar exactamente donde estaba**, con el estado intacto, en otro proceso, quizá en otra máquina, después de un despliegue. Eso no es una pausa: es **persistencia**. Y ya la tienes montada — el checkpointer que pusiste sobre Postgres para no perder trabajo es, sin tocar una línea, el mecanismo completo de intervención humana.

```python
def human_review_gate(state) -> Command[Literal["finalize"]]:
    if not requires_human_review(state):
        return Command(goto="finalize")
    decision = interrupt({
        "reason": build_review_reason(state),
        "estimate": state["estimate"],
        "confidence": state["confidence"],
        "budget_matches": state["budget_matches"],
    })
    return Command(goto="finalize", update={"human_decision": decision, ...})
```

**`interrupt()` no es un `sleep`.** Lanza una excepción de control que LangGraph captura: el estado queda escrito en el checkpoint, la ejecución termina, y el `invoke` que lanzaste te devuelve el control con la información de la interrupción. El proceso queda libre. **El payload que le pasas es lo que verá la persona: ponlo con cuidado, no es un log, es la interfaz.** Un revisor al que le enseñas `confidence: 0.42` y nada más no puede decidir nada; uno al que le enseñas la estimación, el rango histórico con el que choca y los análogos encontrados, sí.

**Reanudar** es el mismo `ainvoke` con el mismo `thread_id`, pasando `Command(resume=human_decision)`. Fíjate en la simetría: `ainvoke` con un input arranca el grafo; `ainvoke` con un `Command(resume=...)` lo continúa. **No hay API especial de reanudación**, porque para LangGraph reanudar no es un caso especial: es lo que hace siempre, partiendo de un checkpoint que resulta que no está vacío. Y usa como `thread_id` el `estimation_id` **del dominio**, no un UUID nuevo: el backend de negocio ya tiene ese identificador, ya lo muestra, y será el mismo que use el revisor. Cuando ese `thread_id` sea también la clave de tus trazas, tendrás un identificador único que atraviesa las tres capas.

## Qué debe parar el grafo (y qué no)

Aquí se decide si tu human-in-the-loop es útil o es teatro. **Las tres señales legítimas:**

1. **Confianza baja.** El validador puntúa su propia certeza — no aparece por arte de magia: se la pides explícitamente, con un esquema y con criterios.
2. **Fuera de rango histórico.** Ni siquiera necesita un modelo: tienes presupuestos indexados, sabes lo que ha costado un CRUD. Es una comparación aritmética.
3. **Sin precedente.** Si ningún presupuesto análogo supera el umbral de similitud, el sistema está estimando a ciegas. No es que se haya equivocado: es que no tiene base sobre la que acertar.

> **La regla que hay debajo:** una señal de disparo es una **condición evaluable sobre el estado**. Si no la puedes escribir como un booleano, no es una señal: es una intuición. Y las intuiciones no se testean, no se ajustan y no se le explican a un cliente.

**Y los tres antipatrones, los tres disfrazados de prudencia:**

- **Un agente ha fallado.** Eso no es una revisión, es un error. Un fallo de tool, un timeout o un JSON mal formado se resuelven con reintento, fallback o degradación. Si mandas los errores a un humano, has convertido a tu revisor en un servicio de reintentos manual, y el día que caiga la API del proveedor le llenarás la bandeja con doscientos casos idénticos. **La distinción es limpia: el error es que el sistema no pudo hacer su trabajo; la revisión es que lo hizo y el resultado necesita juicio.**
- **Revisar por si acaso.** Si el 80% de las estimaciones pasan por revisión, el revisor no revisa: aprueba en automático, en bloque, sin mirar. Y encima has destruido la señal, porque cuando llegue el caso que de verdad importaba llegará indistinguible del resto. **Si todo se revisa, nada se revisa.** Un HITL que dispara en el 5% vale más que uno que dispara en el 60%.
- **Una regla de negocio dura.** "Un socio aprueba cualquier presupuesto por encima de 50.000 €" es un **flujo de aprobación**, y su sitio es el backend de negocio. No lo metas en el grafo. El gate del servicio IA existe para un caso concreto y distinto: **cuando el sistema de IA sabe que no sabe.**

## El contrato: la pausa cruza las tres capas

Esta es la parte que casi todos los tutoriales se saltan, porque en un notebook la reanudación es la siguiente celda. En tu sistema no: la pausa ocurre en el **servicio IA**, la persona decide en el **frontend**, y en medio está el **backend de negocio**, que es quien tiene usuarios, permisos y persistencia. Esa pausa es la primera cosa que **modifica el contrato entre las capas**.

La superficie mínima son dos cosas: **un estado nuevo en la respuesta** y **un endpoint para volver**. `POST /estimations` devuelve `status: "awaiting_human_review"` + `review_payload` cuando el resultado trae `__interrupt__`; `POST /estimations/{id}/resume` reanuda con `Command(resume=payload)`. **El campo `status` no es nuevo: ya estaba en tu contrato; solo le añades un valor posible.** Eso importa más de lo que parece — el backend de negocio no necesita una integración nueva, solo una rama nueva sobre un campo que ya leía. *La arquitectura no cambia; se extiende.*

Y fíjate dónde vive cada responsabilidad: el `authorize!` está en el backend de negocio, porque es quien tiene usuarios y roles. **El servicio IA no sabe quién es un revisor autorizado y no tiene por qué saberlo.** La notificación, la bandeja, el histórico de quién aprobó qué: todo eso es negocio. El servicio IA solo sabe pausar y reanudar. Esa separación no es purismo: es lo que hace que el día que cambies la política de aprobación no tengas que tocar el grafo.

## Lo que te va a morder

- **El nodo se reejecuta desde el principio al reanudar.** El más caro y el menos documentado. LangGraph **no** continúa justo después del `interrupt()`: vuelve a ejecutar el nodo entero desde su primera línea, y esta vez `interrupt()` devuelve el valor en lugar de detener. Consecuencia: **todo lo que hicieras antes del `interrupt()` dentro de ese nodo se ejecuta dos veces**. Si llamabas al modelo, lo pagas dos veces; si insertabas una fila, la insertas dos veces. **La regla: el nodo que interrumpe no hace nada más que interrumpir.** Nada de efectos laterales antes; el trabajo real va en un nodo anterior y el gate solo evalúa una condición y para.
- **Reanudaciones huérfanas.** ¿Y si nadie decide nunca? El checkpoint se queda ahí y la estimación cuelga para siempre en `awaiting_human_review`. Necesitas una política: un plazo, un escalado a otro revisor, una caducidad. No es decisión del servicio IA —es de negocio— pero si no la tomas tú la va a descubrir un cliente.
- **Doble reanudación.** Dos revisores abren la misma estimación y ambos aprueban; la segunda llamada a `resume` llega a un grafo que ya terminó. Tu endpoint tiene que ser **idempotente**, o el backend impedirlo con un bloqueo. Es el problema del doble submit de un formulario, y se resuelve igual: no es un problema de IA.
- **La decisión humana es el dato más valioso que produce tu sistema.** Cada vez que una persona corrige una estimación te está diciendo exactamente en qué se equivoca el modelo, sobre un caso real, con la respuesta correcta al lado. Ese par —lo que el sistema propuso, lo que el humano decidió— sirve para ajustar umbrales, entender qué transcripciones dan problemas y como material de evaluación. **Guárdalo desde el primer día, aunque todavía no sepas qué vas a hacer con él: es gratis ahora e irrecuperable después.**

---

# Parte 5 — Competición y síntesis entre agentes

## El problema: un número sin medida de su propia fragilidad

Tu sistema devuelve 260 horas. ¿Cuánto te fías? No tienes forma de saberlo: la cifra se ve exactamente igual si viene de un caso trivial que el sistema clavó o de un caso imposible sobre el que improvisó con aplomo. **Esa es la debilidad de fondo de un estimador único: no produce ninguna medida de su propia fragilidad.** Puedes pedirle al modelo que puntúe su confianza —es mejor que nada—, pero un modelo evaluando su propia respuesta tiende a confiar en lo que acaba de decir. Hay otra forma de conseguir esa medida, y es más honesta: **hacer que dos agentes con criterios opuestos ataquen el mismo problema y mirar cuánto se separan.**

En estimación de software el ejemplo es casi obsceno de tan natural, porque es lo que ocurre en cualquier reunión real: está el que dice dos semanas y el que dice dos meses, y los dos tienen razón bajo sus supuestos. **El desacuerdo no es un fallo del proceso: el desacuerdo es el proceso.**

## Implementarlo

**Las propuestas tienen esquema.** Si un estimador devuelve un número suelto, el sintetizador solo puede promediar, que es la peor opción. Un estimador devuelve **su número y los supuestos que lo sostienen**:

```python
class EstimateProposal(BaseModel):
    stance: Literal["conservative", "aggressive"]
    hours: float = Field(gt=0)
    assumptions: list[str]   # la carga útil de verdad
    risks: list[str]
    reasoning: str
```

Los `assumptions` son lo valioso. Cuando el conservador dice 340h *porque asume que la integración con el ERP legacy no está documentada* y el agresivo dice 190h *porque asume que el cliente entrega documentación y un entorno de pruebas*, la diferencia entre ambos no es un número: **es una pregunta concreta que alguien puede ir a resolver.**

**Corren en paralelo.** Son independientes: dos aristas desde el mismo nodo, dos aristas hacia el sintetizador. **El fan-in es gratis, y es gratis por el reducer**: `proposals: Annotated[list[dict], operator.add]`. Si ese campo estuviera sin anotar, uno de los dos estimadores desaparecería en silencio y tendrías un sistema de competición **con un solo competidor**. Es el bug más silencioso de todo el tema.

**La divergencia se calcula, no se opina.** La tentación es pasarle las dos propuestas al sintetizador y pedirle que "evalúe cuánto difieren". **No lo hagas.** La divergencia entre dos números es una operación aritmética; pedírsela a un LLM es pagar tokens por una división y encima aceptar que a veces la haga mal.

```python
def compute_divergence(proposals: list[dict]) -> float:
    """Relative spread between proposals. Deterministic, cheap, testable."""
    hours = [p["hours"] for p in proposals]
    lo, hi = min(hours), max(hours)
    return (hi - lo) / hi
```

Una línea. Cero tokens. Y con eso ya tienes, **antes de llamar al sintetizador**, la señal que te faltaba: 190 contra 340 da 0.44; 250 contra 270 da 0.07. Y no es simétrico:

- **Convergen.** Dos criterios deliberadamente opuestos llegan casi al mismo sitio → **el resultado no depende de los supuestos**. Da igual si el equipo es senior o si la integración se tuerce: el proyecto cuesta lo que cuesta. El sistema puede cerrar solo, con confianza alta.
- **Divergen.** El resultado depende por completo de qué supuestos se acepten. No es que el sistema haya calculado mal: **la pregunta no tiene respuesta calculable** sin decidir antes si el cliente entregará la documentación. Eso es un juicio, y un juicio lo toma una persona.

Es decir: la competición no te da solo una estimación mejor. Te da **el criterio para saber cuándo no deberías estar estimando solo**. La divergencia alimenta la confianza, y la confianza alimenta la decisión de parar (Parte 4).

**El sintetizador no promedia.** La instrucción explícita de *no promediar* no es paranoia: es el comportamiento por defecto de un modelo al que le das dos números y le pides uno, y promediar es exactamente lo que destruye el valor de haber pagado dos estimaciones. La media entre 190 y 340 es 265, un número que nadie puede defender y que además **oculta que el rango existe**. Su trabajo es otro: identificar qué supuestos impulsan la diferencia, producir un rango explícito (`hours`, `range_low`, `range_high`), decir qué tendría que ser cierto para moverse hacia un extremo, y reportar su confianza teniendo en cuenta la divergencia. Y `open_questions` es **el campo más útil que produce todo el sistema**: la lista de lo que habría que ir a preguntarle al cliente. Un estimador único jamás la produce, porque no sabe en qué se estaba jugando el número.

## Cuándo esto es un fraude

- **La trampa de la correlación.** Dos agentes con el **mismo modelo, el mismo contexto y prompts que se diferencian en un adjetivo** ("estima de forma conservadora" / "agresiva") producen salidas parecidísimas: has pagado tres llamadas por la ilusión de una segunda opinión. Y lo peor no es el coste: **la divergencia baja resultante es una señal falsa de confianza**. El sistema te dirá que el caso es predecible cuando lo que pasa es que no creaste ninguna diversidad real. Para que valga algo, los competidores tienen que diferir **de verdad**: (a) *prompts con criterios sustantivos*, no adjetivos — al conservador instrucciones sobre integraciones no documentadas y deuda técnica, al agresivo sobre reutilización y equipos con contexto; (b) *evidencia distinta* — el que más impacto tiene y el que menos se usa: dale al conservador los presupuestos históricos **que se pasaron de plazo** y al agresivo los que salieron limpios; ahora no discuten de estilo, miran mundos distintos; (c) *idealmente, modelos distintos* — dos proveedores tienen sesgos distintos. Si no puedes conseguir ninguna de las tres, **no lo montes**.
- **Competir donde no hay nada que juzgar.** Competir en la extracción de requisitos es tirar dinero: hay una respuesta razonablemente correcta y los dos agentes convergerán a ella. **La competición solo aporta cuando hay un juicio de por medio**, es decir, cuando dos personas expertas y razonables podrían discrepar legítimamente. *Regla: si tú no sabrías defender las dos posturas, tus agentes tampoco.*
- **Escalar a N competidores.** Los retornos decaen rápido y el coste es lineal. Con dos criterios genuinamente opuestos ya tienes la banda de incertidumbre; el tercero suele caer en medio. Quédate en dos salvo que puedas nombrar un tercer criterio **de verdad ortogonal**.

**Una alternativa más barata que conviene conocer:** muestrear el mismo prompt varias veces y mirar la dispersión. Más barato, no exige diseñar criterios opuestos, y te da una medida de estabilidad. Lo que *no* te da es lo bueno: no produce supuestos contrapuestos, no produce preguntas abiertas y no te dice **por qué** difieren los números. **El muestreo repetido mide el ruido del modelo; la competición mide la incertidumbre del dominio.** Solo la segunda es accionable con un cliente delante.

## El coste, sin adornos

Un estimador: una llamada. Competición: dos llamadas en paralelo más una síntesis → **tres llamadas y latencia de la más lenta de las dos**. En coste, ×3; en latencia, ≈×2. ¿Merece la pena? Si la salida es un presupuesto que se manda a un cliente y compromete a la empresa durante meses, triplicar el coste de una inferencia para obtener un rango defendible, una lista de supuestos y una medida real de incertidumbre es, con diferencia, el mejor dinero del sistema. Si es una estimación orientativa para priorizar un backlog interno, no: pon un estimador y sigue. **Toda la decisión depende de lo que cueste equivocarse.**

---

# Parte 6 — Mínimo privilegio, validación de acciones y auditoría

## La tesis incómoda: la contención no puede vivir en el prompt

Hasta ahora tus agentes **leen**. Si uno alucina, produce una estimación mala, y una estimación mala la caza el validador o la caza el humano en el gate: el coste de un error es un número equivocado. **Eso cambia por completo el día que un agente escriba.** Alguien añadirá la tool que faltaba —`save_estimate`, `update_budget_status`, `send_estimate_email`— y en ese momento tienes un componente gobernado por un modelo de lenguaje, una máquina que a veces alucina con total aplomo, con permiso para modificar los datos de tu empresa o mandar correos en su nombre. El coste de un error deja de ser un número: pasa a ser una fila borrada, un correo enviado a quien no debía, un estado corrupto en producción.

La reacción instintiva es escribir en el system prompt *"nunca borres datos"*. Es comprensible y es inútil: **un system prompt es una instrucción, no una restricción**. El modelo lo toma como una entrada más, la pondera junto al resto del contexto, y la mayoría de las veces la respeta. *La mayoría de las veces.* Compáralo con cómo proteges cualquier otra cosa: no confías en que el frontend "no envíe" un campo prohibido, lo rechazas en el backend. La regla que llevas toda la vida aplicando —**no confíes en el cliente**— se aplica aquí sin una sola modificación. **El modelo es el cliente**: una entrada no confiable que propone acciones, y las entradas no confiables se validan en una capa que el cliente no controla. Todo lo demás es esa idea aplicada tres veces.

## Capa 1 — Mínimo privilegio en el reparto de tools

Ya la construiste, aunque no la llamaste seguridad: cuando le diste al `budget_searcher` solo `search_budgets`, aplicaste mínimo privilegio. **Si un agente no tiene una tool en la mano, no puede usarla mal por mucho que alucine** — la capacidad no existe en su mundo. La consecuencia de diseño es que **el reparto de tools deja de ser una comodidad y pasa a ser una decisión de seguridad**, y eso obliga a nombrar la naturaleza de cada tool:

```python
class ToolRisk(str, Enum):
    PURE = "pure"          # sin efectos: calculate_estimate
    READ = "read"          # lee estado: search_budgets
    WRITE = "write"        # muta estado: save_estimate
    EXTERNAL = "external"  # actúa sobre el mundo: send_estimate_email

AGENT_TOOL_GRANTS: dict[str, set[str]] = {
    "requirements_extractor": set(),
    "budget_searcher": {"search_budgets"},
    "estimate_generator": {"calculate_estimate"},
    "coherence_validator": {"validate_estimate"},
    "persistence_agent": {"save_estimate"},
}
```

Fíjate en una decisión que va más allá del reparto: **la escritura se saca a un `persistence_agent` propio**. Concentrar las tools de escritura en un único agente pequeño significa que **toda la superficie peligrosa del sistema cabe en un fichero que puedes leer entero en un minuto**. La mayoría de tus agentes se quedan en `read` y `pure` y no hace falta vigilarlos con la misma intensidad. Es la misma lógica por la que aíslas el código que maneja pagos: no porque el resto no importe, sino porque **concentrar el riesgo lo hace revisable**.

Y como **el grant es un dato, no una instrucción**, puedes comprobarlo en el arranque: `verify_tool_grants()` recorre los agentes del grafo y lanza `ConfigurationError` si alguno tiene una tool que no le fue concedida. Un agente al que por error se le cableó una tool que no le corresponde **no llega a producción: rompe el despliegue**. Has convertido una política de seguridad en una invariante que el sistema verifica solo.

## Capa 2 — Validar la acción, no solo tenerla permitida

El mínimo privilegio decide **si** un agente puede usar una tool. No dice nada sobre **con qué argumentos**. El `persistence_agent` tiene permiso para `save_estimate`. ¿Y si el modelo decide guardar una estimación de −400 horas? ¿O sobrescribir un `estimation_id` que no es el de esta ejecución? ¿O guardar un objeto al que le falta la mitad de los campos? Tiene permiso para escribir; **nadie dijo que tuviera permiso para escribir cualquier cosa**.

Hace falta un guardia entre la intención del agente y la ejecución real: un punto por el que pasa toda acción con efectos y que la aprueba o la rechaza **antes** de que toque nada (`guard_action(ActionRequest) -> GuardDecision`). Tres cosas que destacar:

- **El guardia es código plano y determinista.** Nada de un LLM validando a otro LLM: eso solo añade una segunda máquina falible al problema. Las reglas de qué es una acción válida son reglas de negocio, y las reglas de negocio se escriben, se testean y se razonan. **Un test unitario puede cubrir el guardia por completo; no puede cubrir un prompt.**
- **La comprobación de `estimation_id` es la que de verdad importa** y la que más se olvida. Un agente que puede escribir sobre *cualquier* `estimation_id` es un agente que, ante el input adecuado, modifica la estimación de otro cliente. Atar cada acción a la ejecución en curso —el mismo `estimation_id` que ya usas como `thread_id` del checkpointer— convierte un permiso genérico en **un permiso acotado a este contexto**. Es el equivalente a no dejar que un usuario edite recursos que no son suyos.
- **Las acciones irreversibles piden algo más que validación.** Guardar una fila se puede deshacer; enviar un correo al cliente, no. Para esa clase de acciones la validación automática no basta: la decisión correcta es **enrutarlas al gate humano que ya construiste**. Y aquí encajan las dos mitades de la sesión: **el human-in-the-loop no era solo para la baja confianza; es también el mecanismo de aprobación de las acciones que no admiten marcha atrás.** No hay que inventar nada nuevo: la misma pausa, disparada por otra señal.

## Capa 3 — Auditoría, porque lo que no se registra no ocurrió

Las dos primeras capas previenen; la tercera no previene nada: **hace que todo sea reconstruible después**. Y es la que separa un sistema que puedes operar de uno para el que solo puedes rezar. Cuando un cliente pregunte por qué cambió su estimación, la respuesta no puede ser "no sé, el modelo decidió eso".

**La regla es tajante: toda acción con efectos se registra, incluidas las que el guardia denegó.** Las denegadas son de hecho las más valiosas: son el sistema diciéndote exactamente dónde un agente intentó salirse de su carril, y **una tasa de denegaciones que sube es una alarma temprana**, mucho antes de que nada se rompa. El envoltorio `execute_guarded()` es el único camino: pide la decisión al guardia, liga el log (`agent`, `tool`, `args` redactados, `estimation_id`, `allowed`), y o bien registra `action_denied` y lanza `ActionDeniedError`, o ejecuta y registra `action_executed`. El registro lleva el `estimation_id` —otra vez, el mismo identificador que atraviesa las tres capas y tus trazas—, con lo que reconstruir lo que hizo el sistema para un caso concreto es **una consulta, no una arqueología**. Y `redact_sensitive` está ahí por una razón que no conviene aprender por las malas: **un log de auditoría que copia datos personales del cliente en texto plano es él mismo un problema de privacidad.** Auditas la *acción* —quién, qué tool, con qué forma de argumentos, con qué resultado—, no el contenido íntegro de los datos.

## Qué es y qué no es "sandboxing" aquí

Conviene ser honesto sobre lo que esta sesión cubre, porque confundirlo genera una falsa sensación de seguridad, que es peor que no tener ninguna. Hay **dos fronteras de seguridad, no una**:

| Nivel de agente (esta sesión) | Nivel de infraestructura (siguiente sesión) |
|---|---|
| Cada agente accede solo a sus tools | Aislamiento de proceso y contenedor |
| Validación de cada acción antes de ejecutar | Políticas de red y egress |
| Confirmación de acciones irreversibles | Límites de recursos (CPU, memoria, tiempo) |
| Auditoría de toda intención, permitida o no | Secretos, credenciales, rotación |
| Responde a: *qué puede hacer este agente dentro de la lógica de la aplicación*. Vive en tu código Python. | Responde a: *qué daño puede hacer el proceso si un agente se comporta de forma imprevista*. Vive en el runtime y el despliegue. |

**No se sustituyen, se complementan, y ninguna sola es suficiente.** La validación de acciones no te protege de un agente que ejecuta código arbitrario a través de una tool mal diseñada; para eso hace falta aislamiento de proceso. Y el aislamiento no te protege de un agente que guarda una estimación negativa con argumentos perfectamente válidos desde el punto de vista del sistema operativo; para eso hace falta validación de dominio.

## Cierre del módulo

El recorrido tiene una forma: empezaste con un grafo lineal que hacía su trabajo; lo cuestionaste (*¿por qué complicarlo?*) y solo cuando aparecieron límites concretos —prompts sobrecargados, rutas que dependen del caso, decisiones que el código no puede prever— lo reorganizaste en un supervisor que enruta y unos agentes que se especializan. Elegiste cómo se comunican sabiendo que la pizarra compartida que ya tenías era el punto de partida correcto. Le diste al sistema la capacidad de **pararse y pedir ayuda** cuando sabe que no sabe, apoyándote en el mismo checkpointer de siempre. Aprendiste a hacer que los agentes **compitan** cuando el desacuerdo es información. Y le pusiste **límites a lo que cada agente puede tocar**, validación a lo que hace y un registro de todo ello.

**Nada de eso fue un paradigma nuevo.** Cada pieza resultó ser un principio de ingeniería conocido aplicado a un componente que a veces alucina: separación de responsabilidades, contratos entre capas, no confiar en el cliente, persistencia para sobrevivir a los fallos, defensa en profundidad. La capa genuinamente nueva era pequeña. *Ese era el trato desde el principio.*

---

# Chuleta de una página

| Concepto | Qué es / resuelve | Cuándo SÍ | Cuándo NO | Coste / palanca |
|---|---|---|---|---|
| **Multi-agente** | Reorganización del grafo: un nodo decide, varios se especializan | Prompt sobrecargado, >6 tools en un nodo, orden desconocido, ritmos de cambio distintos | Flujo fijo, prompt malo, sin observabilidad | Latencia, tokens de enrutado y coste cognitivo |
| **Supervisor** | Nodo sin tools que descompone, delega y consolida | La ruta varía de verdad entre casos | Su política es "A, luego B, luego C" | +100% de llamadas en topología plana |
| **Digest de estado** | Proyección de 5 líneas del estado para decidir | Siempre que enrutes con modelo | Pasar el historial completo (crece sin control) | Coste **constante** por decisión |
| **`Command(goto, update)`** | Mueve control y estado en una sola operación | Enrutado como decisión del nodo | Cuando una arista estática ya lo expresa | El `Literal` de destinos debe estar sincronizado |
| **`MAX_ROUTING_STEPS`** | Techo de saltos de enrutado | **Siempre**, desde la primera línea | — | Sin él, el bucle infinito es el default |
| **`routing_trail`** | Acumulador de `next_agent` + `reason` | Trazas y tests de invariantes | — | `operator.add`; testea el resultado, no el camino |
| **Supervisor híbrido** | Reglas para precondiciones, modelo solo ante ambigüedad real | Casi siempre (la opción aburrida que gana) | Cuando toda bifurcación es un juicio | Más barato, rápido, predecible y testeable |
| **Plano vs jerárquico** | 1 supervisor + N agentes / equipos con sub-supervisores | Plano por defecto; jerárquico con ~15 opciones | Empezar en jerárquico | Un nivel = una llamada más por salto |
| **Estado compartido (blackboard)** | Todos escriben en la pizarra, nadie se habla | **Por defecto.** Mejor trazabilidad por unidad de complejidad | Cuando el estado ya es un objeto Dios (→ proyecciones) | Acoplamiento solo al esquema |
| **Reducer** | Política ante escrituras concurrentes | Acumular donde varios aportan | Sobrescribir donde acumula = pérdida silenciosa | Decide campo a campo, conscientemente |
| **Handoff (swarm)** | El agente elige a quién pasa el testigo | Enrutado central = cuello de botella **medido** | Por elegancia | 2 llamadas en vez de 4; acoplamiento topológico |
| **`graph=Command.PARENT`** | Hace que el `goto` escape del subgrafo | Siempre en handoff a mano | — | Error nº 1 si se olvida |
| **`task_brief`** | Qué contexto viaja en el testigo | Brief destilado y explícito | Pasar todo el historial (default de las librerías) | Lo que no esté, no existe para el que viene |
| **Mensajes / bus** | Publicar eventos; nadie llama a nadie | Los agentes cruzan la frontera del **proceso** | Mientras vivan en el mismo servicio | Consistencia eventual + `correlation_id` + operación |
| **`interrupt()`** | Persiste el estado, termina la ejecución, libera el proceso | Confianza baja, fuera de rango, sin precedente | Errores, "por si acaso", reglas de negocio duras | El payload **es la interfaz** del revisor |
| **`Command(resume=...)`** | Continúa desde el checkpoint | Mismo `ainvoke`, mismo `thread_id` | — | `thread_id` = `estimation_id` del dominio |
| **Nodo del gate** | Solo evalúa condición e interrumpe | Efectos laterales en un nodo anterior | Trabajo antes del `interrupt()` | **Se reejecuta entero** al reanudar |
| **Competición + síntesis** | Dos criterios opuestos + un sintetizador | La salida compromete a la empresa; hay juicio de por medio | Tareas con respuesta correcta; estimación orientativa | ×3 coste, ×2 latencia |
| **Divergencia** | `(hi−lo)/hi` sobre las propuestas | **Siempre en código**, antes de sintetizar | Pedírsela a un LLM | Alimenta la confianza y la decisión de parar |
| **Diversidad real** | Prompts sustantivos + evidencia distinta + modelos distintos | Precondición para que la competición valga | Dos prompts que difieren en un adjetivo | Divergencia baja falsa = confianza falsa |
| **Mínimo privilegio** | Cada agente, solo sus tools | Siempre; escrituras en un único agente | Repartir writes entre varios | `verify_tool_grants()` rompe el despliegue |
| **Action guard** | Valida agente + tool + **argumentos** + `estimation_id` | Toda acción con efectos | Un LLM validando a otro LLM | Código determinista, cubierto por tests |
| **Auditoría** | Registro de toda intención, permitida o **denegada** | Siempre | Loguear datos personales en claro (`redact_sensitive`) | Las denegaciones son alarma temprana |

**La meta-lección, otra vez:** *no subas un escalón hasta que el anterior te falle de forma medida.* Grafo lineal → supervisor cuando la ruta varía de verdad. Estado compartido → handoff cuando el enrutado sea un coste medido → mensajes cuando cruces el proceso. Un estimador → competición cuando el error sea caro. Y ninguna contención en el prompt: **el modelo es el cliente**, y al cliente no se le cree, se le valida.

---

## Cómo conecta con nuestro ejercicio

Estado actual del repo: `session-14` sobre el port completo de `session_13_live` (grafo multi-agente con handovers e HITL), **470 tests**.

> **Nota posterior.** Este diagnóstico se escribió **antes** de resolver el ejercicio. Los Niveles 1, 2 y 3 ya están portados (supervisor a mano, mínimo privilegio, puerta condicional, auditoría) en `app/domain/graph/supervisor/` — ver [`session-14-exercise-supervisor-multiagente.md`](session-14-exercise-supervisor-multiagente.md). Sigue en pie lo que el enunciado difiere al directo: **competición + síntesis** (Parte 5) y el hardening de sandboxing (Parte 6). Y el orden de port que proponía el último punto de esta sección resultó ser el del propio enunciado, salvo que el supervisor va primero, no último.

- **Ya cruzamos parte de la frontera de la Parte 1, pero por handovers cableados, no por un supervisor.** `app/domain/graph/build.py` declara ocho nodos con **una sola arista desde `START`** y dos transiciones vía `Command(goto=...)` (`classifier_agent → structure_agent` y `recover_and_handover → analysis_agent`). Es el mecanismo de la Parte 2, pero el destino está **fijado en el código de cada nodo**, no elegido en runtime: el orden lo sigue decidiendo el fichero. Según el criterio de la Parte 1 seguimos siendo, estrictamente, un workflow con nodos-agente.
- **No existe supervisor, ni digest, ni presupuesto de enrutado.** No hay ningún nodo `supervisor`, ni `SupervisorDecision`, ni `AgentName = Literal[...]`, ni `routing_steps`/`routing_trail`/`MAX_ROUTING_STEPS`, ni `build_state_digest`. Es la brecha literal de la Parte 2 — y la pregunta honesta que el propio artículo obliga a hacerse antes de portarlo: **¿varía la ruta de verdad?** Hoy la única ambigüedad real del flujo es la recuperación de tareas flagged (`recover_and_handover`), que ya se resuelve por reglas. El resto son **precondiciones** — justo el caso donde el artículo recomienda el supervisor híbrido o, directamente, no tener supervisor.
- **La Parte 3 la tenemos resuelta en el escalón correcto: estado compartido.** `EstimationState` (`app/domain/graph/state.py`) es literalmente la pizarra del blackboard, con la disciplina de reducers que el artículo pide: `budget_matches` y `errors` acumulan con `operator.add`, y `task_hours` usa **`merge_task_hours`, un reducer keyed por `(module, task)` last-write-wins** — que es más de lo que el artículo exige, porque además es idempotente ante reanudaciones. No hay handoff con tools (`Command.PARENT` no aparece en ningún sitio) ni bus de eventos, y por el criterio de la Parte 3 **está bien así**: los agentes viven en el mismo proceso y el enrutado central todavía no es un cuello de botella medido.
- **El HITL de la Parte 4 ya está montado, y el nodo del gate cumple la regla más cara.** `app/domain/graph/agents/gates.py` llama a `interrupt()` **como primera instrucción** de ambos gates y solo escribe campos plain last-write-wins después — exactamente la disciplina que el artículo describe ("el nodo que interrumpe no hace nada más que interrumpir"), y el docstring ya documenta el porqué (la reejecución del nodo al reanudar). El contrato entre capas también está: `POST /v1/estimate/graph/...` devuelve el payload de interrupción y hay endpoint de `resume` con `Command(resume=...)`, con `thread_id = estimation_id` del dominio.
- **Pero nuestros dos gates son incondicionales, y eso es el antipatrón "revisar por si acaso" leído al pie de la letra.** Ni `human_gate_structure` ni `human_gate_analysis` evalúan ninguna señal: **el 100% de las ejecuciones para en ambos**. No existe `requires_human_review(state)`, ni umbral de confianza, ni comprobación de rango histórico, ni "sin precedente" como condición booleana. Matiz honesto: en nuestro caso es **deliberado** —el flujo es un wizard donde la persona *es* el usuario que edita el árbol y completa la estimación—, así que no es un HITL de IA mal calibrado sino un flujo de producto. La brecha real es que **no tenemos además el gate condicional del artículo**: el que dispara solo cuando el sistema sabe que no sabe. Los ingredientes ya están en el estado (`confidence`, `analysis_report`, `budget_matches` vacío = sin precedente); falta escribirlos como booleano.
- **De la Parte 5 tenemos la mitad conceptual, pero sobre evidencia, no sobre agentes.** `app/generation/rag/quality/synthesis.py` (S11) ya hace lo esencial: mide la **dispersión** entre análogos históricos de forma determinista, la compara con `SYNTHESIS_CONTRADICTION_THRESHOLD` (0.35) y, solo si la cruza, emite un `HourRange(low, high, reason)` en vez de un punto falsamente preciso — con fallback determinista si el LLM está desactivado. Es exactamente la filosofía "la divergencia se calcula, no se opina" y "el sintetizador no promedia". **Lo que no tenemos es la competición**: no hay `conservative_estimator` / `aggressive_estimator` / `synthesizer` (cero coincidencias en el código), ni `EstimateProposal` con `assumptions`, ni `proposals` como campo acumulador, ni `open_questions`. Nuestra divergencia mide desacuerdo **entre presupuestos históricos**; la del artículo mide desacuerdo **entre supuestos**, y solo la segunda produce la lista de preguntas para el cliente.
- **Las `personas` del grafo son diversidad estética, no diversidad de criterio.** `app/domain/graph/personas.py` da voz Matrix a cada nodo con un guardrail explícito de no sacrificar corrección. Conviene tenerlo claro a la luz de la Parte 5: eso es **exactamente el tipo de diferenciación que el artículo llama "la trampa de la correlación"** si se usara para competir — prompts que difieren en el tono, no en el criterio ni en la evidencia. Como framing didáctico está bien; como base de una competición no serviría.
- **De la Parte 6 no hay nada, y hoy el riesgo es bajo por accidente, no por diseño.** Las tres tools de S12 (`app/generation/agentic/agent_tools.py`: `search_budgets`, `derive_task_hours`, `validate_estimate`) son todas `READ`/`PURE` — no hay ninguna tool de escritura ni de envío, y los nodos del grafo de S13 ni siquiera usan function calling (llaman al modelo con `response_model` tipado). No existe `ToolRisk`, ni `AGENT_TOOL_GRANTS`, ni `verify_tool_grants()`, ni `guard_action`, ni `execute_guarded`, ni log de auditoría de acciones. **Es la brecha más limpia de la sesión**: hoy no duele porque nadie escribe, y el artículo avisa de que el día que alguien añada `save_estimate` la decisión ya estará tomada por omisión. La comprobación de `estimation_id` es además gratis en nuestro caso: ya lo usamos como `thread_id` del checkpointer.
- **La observabilidad, que la Parte 1 marca como precondición, sí está.** Logfire está cableado en `app/main.py` y en los ocho nodos del grafo (`logfire.span("node: ...")`), además de structlog con `request_id`. Es decir: cumplimos el "si no tienes observabilidad, no añadas agentes" — lo que falta para el patrón supervisor es el atributo que hoy no existe porque no hay decisión que registrar (`next_agent` / `reason`).
- **Qué portaría, por orden de valor.** (1) El **guardia + grants + auditoría** de la Parte 6, aunque hoy no haya writes: es barato, determinista, cubierto por tests unitarios y convierte una política en invariante de arranque. (2) La **competición conservador/agresivo con divergencia calculada** de la Parte 5, reutilizando `compute_divergence` sobre nuestro `synthesis.py` existente y con evidencia distinta (presupuestos desviados vs. limpios) para evitar la trampa de la correlación. (3) El **gate condicional** de la Parte 4 (`requires_human_review`), que además conecta con (2): la divergencia alimenta la confianza y la confianza dispara la pausa. (4) El **supervisor** de la Parte 2 — el último, y solo en su versión **híbrida**, porque por nuestro propio flujo casi todas las bifurcaciones son precondiciones y el artículo es explícito: si al escribirlo no aparece ninguna ambigüedad real, lo que necesitas es el grafo que ya tenías.
