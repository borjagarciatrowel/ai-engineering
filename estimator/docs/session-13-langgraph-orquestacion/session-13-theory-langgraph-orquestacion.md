# Sesión 13 — Del bucle al grafo: LangGraph, estado, paralelismo, errores y observabilidad (versión clara)

> Versión simplificada del resumen de los 6 artículos de la Sesión 13.
> Misma información, menos paja. Cada término técnico se explica en una frase.
> **Hilo conductor:** la Sesión 12 dejó al sistema con un bucle agéntico a mano — function calling, un `while`, unas cuantas ramas — construido sobre el pipeline RAG de las sesiones 9-11. Funciona bien mientras el flujo es corto. La Sesión 13 se pregunta qué pasa cuando ese bucle crece: varios pasos con dependencias, ramas condicionales, trabajo paralelizable, reintentos, un humano que a veces tiene que decidir. La respuesta no es "usa un framework porque sí": es aprender a reconocer cuándo el bucle imperativo se rompe y, si se rompe, cómo se reexpresa como un grafo — estado tipado, nodos, aristas, persistencia, paralelismo, recuperación de errores y, por fin, la capacidad de verlo todo por dentro.

---

## Glosario base (léelo una vez y vuelve cuando haga falta)

| Término | Qué es, en una frase |
|---|---|
| **Framework de orquestación** | Herramienta que coordina pasos, estado y errores con abstracciones ya hechas; no aporta magia, resuelve ingeniería de sistemas ya conocida. |
| **Orquestación basada en grafos** | Modelas el flujo como un grafo dirigido: nodos que trabajan, aristas que deciden. Exponente: LangGraph. |
| **`StateGraph`** | El constructor de LangGraph: le das un esquema de estado, le añades nodos y aristas, lo compilas y obtienes un grafo ejecutable. |
| **Estado** | Objeto compartido y tipado (`TypedDict`) que todos los nodos leen y actualizan; la decisión de diseño de más peso en un grafo. |
| **Nodo** | Una función pura: recibe el estado, devuelve solo los campos que cambia. No orquesta, solo trabaja. |
| **Arista** | Conexión entre nodos. Directa: fija una secuencia. Condicional: una función que mira el estado y decide a dónde ir. |
| **Reducer** | La regla de cómo se combina una actualización con el estado existente. Por defecto sobrescribe; `operator.add` acumula (concatena). |
| **Checkpointer** | Persiste el estado tras cada nodo. Da pausa, reanudación e inspección sin que escribas tú una capa de base de datos. |
| **`thread_id`** | La clave que ata una ejecución a su historia de checkpoints. Mismo id, se reanuda; id distinto, ejecución limpia. |
| **Memoria corta / larga** | Corta: estado de una ejecución, vive en el checkpointer, efímera. Larga: historial de negocio entre ejecuciones, vive en tu base de datos de producto — no son lo mismo. |
| **Send API / fan-out** | Patrón para paralelizar trabajo por elemento: se despacha una rama de ejecución por cada ítem, todas a la vez. |
| **Fan-in** | La convergencia de las ramas paralelas: el reducer combina lo que cada una devolvió en un único resultado. |
| **Ciclo acotado** | Una arista condicional que vuelve atrás (reintento, replanificación) con un tope explícito, no solo con la red de seguridad del framework. |
| **`interrupt`** | Pausa el grafo en mitad de un nodo, persiste el estado y espera una decisión humana antes de continuar. |
| **Circuit breaker** | Deja de llamar a una dependencia que falla de forma persistente durante un tiempo de enfriamiento, en vez de reintentar sin fin. |
| **Span / traza** | Un span mide un tramo de ejecución (nombre, inicio, fin, atributos); el árbol de spans es la traza completa de una petición. |

---

## La idea en una página

El bucle a mano de la Sesión 12 no estaba mal hecho: es la respuesta correcta para un agente de un solo tipo de decisión iterando en bucle. Lo que cambia en la Sesión 13 no es la calidad del bucle, es su **forma**. En cuanto el flujo tiene pasos con dependencias, ramas condicionales de verdad y trabajo paralelizable, seguir escribiéndolo como `if` anidados dentro de un `while` es la decisión que se paga en legibilidad, no la que ahorra trabajo.

| # | El tema | El artículo |
|---|---------|-------------|
| 1 | **¿Cuándo un bucle a mano deja de bastar?** El panorama de frameworks en 2026 (grafos, roles, conversacional), y el criterio real: no es moda, es la forma del flujo. | **Del bucle manual al grafo** (Parte 1) |
| 2 | **¿Cómo se construye un grafo desde cero?** Cuatro primitivas — estado, nodo, arista, checkpointer — y nada más. El esquema de estado es la decisión que más pesa. | **LangGraph desde cero** (Parte 2) |
| 3 | **¿Cómo sobrevive el estado a un reinicio?** Reducers que combinan, checkpointers que persisten sobre el Postgres que ya tienes, y la distinción entre memoria corta y memoria larga. | **Estado y persistencia** (Parte 3) |
| 4 | **¿Cómo se deja de esperar en fila?** Fan-out con la Send API, fan-in vía reducer, aristas condicionales y ciclos acotados. | **Ejecución paralela y enrutado condicional** (Parte 4) |
| 5 | **¿Qué pasa cuando algo se rompe?** Cuatro tipos de fallo, cuatro respuestas distintas: reintento, fallback/circuit breaker, reanudación desde checkpoint, puerta humana con `interrupt`. | **Manejo de errores y recuperación** (Parte 5) |
| 6 | **¿Cómo se ve la ejecución por dentro?** Spans, trazas, LangSmith frente a Logfire, y por qué un servicio full-stack necesita ver más que la capa del modelo. | **Observabilidad** (Parte 6) |

> **El hilo que atraviesa las seis partes:** un grafo no sustituye la ingeniería del bucle a mano, la hace explícita. El trabajo vive en los nodos, el control vive en las aristas, el dato vive en un estado tipado que se persiste solo. Nada de esto es gratis — hay un diseño previo que pagar y un impuesto de complejidad real —, y la sesión entera insiste en la misma disciplina: **mide la línea base antes de decidir, y adopta cada pieza (grafo, paralelismo, checkpointer, puerta humana, observabilidad) solo cuando la forma del problema te obliga.**

---

# Parte 1 — Del bucle manual al grafo: cuándo necesitamos un framework

## Por qué el bucle a mano deja de alcanzar

El bucle de la Sesión 12 — `while` con function calling, unas cuantas ramas — funciona bien mientras el flujo es corto. El problema aparece cuando crece: varios pasos con dependencias, decisiones condicionales que dependen de lo que devolvió el paso anterior, trabajo paralelizable, situaciones en las que hay que volver atrás. El código sigue siendo correcto, pero acumula `if` anidados, banderas de estado y comentarios que explican el orden — deja de ser fácil de razonar cuando algo falla en producción.

## El panorama de frameworks en 2026

Tres modelos conviven: **orquestación basada en grafos** (LangGraph, 1.0 estable desde octubre de 2025 — flujo explícito, control determinista, más diseño previo), **basada en roles** (CrewAI — agentes como personas de un equipo, modelo mental intuitivo, se prototipa rápido, menos control fino con ramificación compleja) y **conversacional** (linaje AutoGen, hoy fusionado con Semantic Kernel en el Microsoft Agent Framework 1.0, natural en Azure/.NET). Fuera de esos tres: Google ADK (code-first, model-agnostic, agentes de flujo secuencial/paralelo/bucle) y Pydantic AI (nativo de Python, tipado, inyección de dependencias al estilo FastAPI). **La novedad de todos ellos está acotada:** resuelven variaciones del mismo problema —coordinar pasos, mantener estado, recuperar de errores— con abstracciones distintas. Ninguno hace magia.

## La pregunta correcta

No es "framework sí o no": es **¿qué forma tiene mi flujo?** El patrón que domina en producción es híbrido — framework para el 80% estándar del flujo, código propio para el diferencial de dominio —, y el consejo más repetido es igual de sobrio: empieza simple, instrumenta mucho, añade complejidad solo donde los datos la exijan. Un dato ordena las prioridades: según el informe de LangChain de 2026, **más del 60% de los incidentes de agentes en producción se originan en la gestión de estado**, no en el modelo ni en el prompt. Eso es lo que un framework tiene que resolver bien para ganarse su sitio.

## Dónde encaja LangGraph, y dónde no

Conviene separar dos niveles. El atajo de alto nivel `create_agent` (sucesor de `create_react_agent`) construye en pocas líneas un agente ReAct de bucle único — para eso, un bucle a mano o `create_agent` sirven igual de bien. La API de bajo nivel, `StateGraph`, es otra cosa: da forma explícita a topologías que el bucle ReAct no expresa bien — pasos con dependencias, enrutado condicional, paralelismo, ciclos acotados. **Ahí es donde el grafo se gana su sitio.**

La regla práctica: una sola llamada al modelo con formato de salida → sin framework, no hay nada que orquestar. Un agente único que razona y llama tools en bucle → bucle a mano bien instrumentado, el framework aporta poco. Pasos con dependencias, ramas condicionales, paralelismo, necesidad de persistir y reanudar estado, puntos de aprobación humana → ahí el framework ahorra exactamente el trabajo que, si no, reimplementarías peor. Y una prueba que no se salta: **mide la línea base.** Si reexpresar el bucle como grafo no gana nada medible, el bucle ya era la respuesta correcta.

---

# Parte 2 — LangGraph desde cero: StateGraph, nodos, aristas y estado

## Cuatro primitivas y nada más

LangGraph separa lo que el bucle a mano mezclaba: **el trabajo vive en los nodos, el control vive en las aristas, el dato vive en un estado compartido.** Son cuatro piezas: **estado** (objeto tipado que todos leen y actualizan), **nodo** (función que recibe el estado y devuelve una actualización parcial), **arista** (directa fija secuencia; condicional decide mirando el estado) y **checkpointer** (persiste tras cada paso). `StateGraph` es el constructor que junta las tres primeras: lo instancias con un esquema de estado, añades nodos, dibujas aristas, fijas el punto de entrada y compilas.

## El estado: la decisión más consecuente

Es un `TypedDict` (también vale Pydantic o dataclasses). La clave está en los campos **anotados**: por defecto un campo se sobrescribe (el último valor manda — correcto para `status` o `estimate`), pero para un campo que debe acumular (`budget_matches`, donde cada búsqueda aporta resultados que deben sumarse) se usa `Annotated[list[BudgetMatch], operator.add]`. Ese reducer es lo que hace que la ejecución en paralelo tenga sentido: varias ramas pueden escribir a la vez sin pisarse. Disciplina que ahorra disgustos: **mantén el estado ligero** — todo se serializa en cada transición; guarda identificadores y datos ya destilados, no respuestas crudas del modelo.

## Nodos y aristas

Un nodo es una función pura: recibe el estado, devuelve solo los campos que cambia, no muta lo que recibe. Eso lo hace trivial de testear y mantiene el enrutado predecible — reutiliza la lógica de dominio que ya existe (recuperación, cálculo), envuelta en esta forma. Las aristas directas fijan el orden cuando el orden es fijo; las condicionales son una función que inspecciona el estado y devuelve el nombre del siguiente nodo — el mismo mecanismo que después soporta reintentos, ciclos y bifurcaciones más ricas. `START` y `END` son los centinelas. Compilar produce un grafo ejecutable; el estado tipado es el contrato que atraviesa toda la ejecución.

## El coste del diseño previo

Un bucle a mano se escribe de un tirón; un grafo obliga a decidir de antemano el esquema de estado, qué es un nodo y dónde va una arista condicional. Ese diseño previo es trabajo real y para un flujo trivial no rinde. La contrapartida es que es exactamente lo que da el control después. Tres reglas mantienen el grafo sano: reducers solo donde de verdad se acumula, aristas condicionales solo en puntos de decisión reales, estado mínimo y tipado. Un grafo que las respeta se lee de un vistazo y se depura por nodo.

---

# Parte 3 — Estado y persistencia: reducers, checkpointers y memoria

## Por qué el estado en memoria no basta

Si el estado vive solo en memoria, basta con que el proceso se reinicie a mitad de una estimación —un despliegue, un fallo, un timeout— para perder todo el trabajo hecho hasta ahí. Persistirlo es lo que convierte el grafo en algo que aguanta producción, y el dato que lo justifica es el mismo de la Parte 1: **más del 60% de los incidentes de agentes en producción se originan en la gestión de estado.**

## Reducers: el detalle que muerde en producción

Un campo acumulador sobrevive a los reinicios combinándose con lo que ya había; uno de sobrescritura toma su último valor. El detalle que muerde: **al reanudar una ejecución desde un checkpoint, si pasas un estado inicial que incluye campos acumuladores, el reducer no reemplaza — combina.** El resultado es duplicar datos sin darte cuenta (`operator.add` concatena lo nuevo con lo ya guardado). La regla: al reanudar, pasa solo las entradas nuevas, nunca los campos acumulados.

## Checkpointers: persistencia sin escribir una capa de base de datos

Un checkpointer persiste el estado **tras la ejecución de cada nodo**, habilitando pausar, reanudar, inspeccionar paso a paso y, más adelante, aprobación humana — sin que tengas que escribir tú esa capa. Backends: `InMemorySaver` (dev/tests), `SqliteSaver` (un solo servidor), `PostgresSaver`/`AsyncPostgresSaver` (producción con varias instancias; la variante asíncrona es la que casa con un stack FastAPI + asyncpg). **Punto clave para cualquier proyecto que ya tenga pgvector:** el checkpointer se apoya en el mismo PostgreSQL, crea sus propias tablas y convive sin roces — no hay infraestructura nueva que levantar. El `thread_id` ata cada ejecución a su historia: mismo id, se reanuda desde el último checkpoint; id distinto, ejecución limpia.

## Memoria corta y memoria larga no son lo mismo

Confundirlas lleva a malas decisiones de arquitectura. **Memoria corta:** el estado de una ejecución, atado a su `thread_id`, vive en el checkpointer, es efímera — su propósito es operativo (reanudar, inspeccionar, aprobar). **Memoria larga:** el historial de negocio a lo largo del tiempo, que sirve de contexto para el futuro — dato durable que vive donde vive el dato de negocio, no en las tablas de checkpoints. **El checkpointer no es tu base de datos de producto.** Reanudar una ejecución y recordar el historial son dos problemas distintos; mezclarlos ensucia los dos.

## El coste de un estado gordo

Todo lo que hay en el estado se serializa **en cada transición entre nodos**. Un estado ligero se serializa en milisegundos; uno que arrastra respuestas crudas del modelo puede crecer a cientos de kilobytes o megabytes, y la escritura del checkpoint pasa de milisegundos a cientos, convirtiéndose en el cuello de botella real. El agente no va lento por el modelo — va lento porque en cada paso serializa un objeto enorme. Es la misma disciplina de siempre (IDs, resultados destilados, nada transitorio), vista ahora desde el coste de serialización.

---

# Parte 4 — Ejecución paralela y enrutado condicional

## Fan-out con la Send API

Cuando un paso recorre una lista de elementos independientes (buscar el presupuesto de cada componente, uno por uno), ejecutarlo en serie se paga en latencia sin recibir nada a cambio. El patrón es **fan-out**: en lugar de un nodo que recorre la lista, se despacha una rama por elemento, todas a la vez, con la **Send API**. Se divide el paso en dos piezas: una función de despacho que emite un `Send` por cada componente hacia un nodo trabajador, y el trabajador procesa **un solo** elemento. LangGraph ejecuta todos los `Send` en paralelo.

## Fan-in: el reducer es lo que lo hace posible

Aquí el reducer del artículo anterior deja de ser un detalle y pasa a ser lo que **hace posible el paralelismo**. Cada rama devuelve `{"budget_matches": [match]}`; si el campo fuera de sobrescritura, las ramas se pisarían y solo sobreviviría el último resultado. Anotado con `operator.add`, LangGraph concatena las salidas de todas las ramas — el nodo siguiente se ejecuta una sola vez, cuando todas han terminado, con todo reunido. El impacto: ocho recuperaciones que antes iban en fila ahora ocurren a la vez, y el tiempo del paso pasa de la suma de todas a, aproximadamente, la más lenta.

## Aristas condicionales y ciclos acotados

El paralelismo resuelve "hacer varias cosas a la vez"; la arista condicional resuelve "decidir qué va después" — el mismo mecanismo que despacha el fan-out, usado ahora para bifurcar. Punto de decisión típico: tras validar, si pasa el flujo termina, si no se desvía a revisión. La función de enrutado no hace trabajo, solo lee el estado y decide — poner aristas condicionales solo en puntos de decisión reales es lo que mantiene el grafo legible.

Las aristas condicionales permiten **volver atrás** (reintentar con otros parámetros), algo que un pipeline lineal no permitía. El peligro es el bucle infinito con una factura infinita detrás. LangGraph trae un `recursion_limit` global como red de seguridad, pero **la estrategia real es un contador de intentos en el estado** y una función de enrutado que, superado el tope, abandona limpiamente hacia revisión — el ciclo tiene una salida garantizada por diseño, no solo por el framework.

## El coste del paralelismo

Paralelizar no sale gratis: el coste está en el **merge del estado**. Dos disciplinas obligatorias: los campos con escrituras concurrentes tienen que ser acumuladores (uno de sobrescritura bajo paralelismo es un bug esperando a ocurrir), y cada rama debe devolver una forma compatible con lo que el agregador espera — un trabajador que solo toca su campo acumulador es trivial de combinar; uno que además toca `status` o `estimate` mete condiciones de carrera donde no las había. El paralelismo premia el estado limpio y castiga el que arrastra campos de más.

---

# Parte 5 — Manejo de errores y recuperación en flujos complejos

## Cada tipo de fallo pide una respuesta distinta

Meter todos los fallos en el mismo saco lleva a reintentar lo que no se arregla solo, o a rendirse ante lo que un reintento habría resuelto. Cuatro categorías, cuatro respuestas:

- **Fallo transitorio** (pico de latencia, corte momentáneo) → reintentar con backoff.
- **Dependencia caída de forma persistente** → reintentar solo alarga la agonía; la respuesta es un camino de **fallback** y, si conviene, un **circuit breaker** que deje de golpear la dependencia rota durante un enfriamiento.
- **Excepción en un nodo** → detiene la ejecución, pero como el estado está persistido hasta el último nodo que terminó, no se pierde el trabajo: se reanuda desde ahí.
- **Baja confianza o ambigüedad** (no es un fallo técnico, es una parada) → lo correcto no es que el sistema decida solo, sino **parar y preguntar a un humano**.

## Reintentos, timeouts y fallback

LangGraph permite adjuntar una `RetryPolicy` a un nodo — el framework lo reejecuta ante un fallo, con backoff exponencial, sin que escribas el bucle de reintento. Los timeouts son responsabilidad del nodo (es quien conoce la operación que puede colgarse); la clave es **degradar con gracia**: una búsqueda que agota su tiempo registra el hueco en el campo de errores (que es un acumulador, no una excepción que se propaga) y deja que el flujo siga — las demás ramas aportan sus resultados, el nodo de estimación recibe el conjunto con la información de qué falta. A nivel de dependencia externa, el circuit breaker evita que cada ejecución pague el coste de redescubrir que la base sigue caída.

## La puerta humana: `interrupt`

`interrupt` pausa el grafo en mitad de un nodo, persiste el estado y expone un valor a quien invocó — la ejecución espera, indefinidamente si hace falta, hasta que alguien la reanuda con `Command(resume=...)`. Necesita checkpointer: sin persistencia no hay dónde guardar el punto de pausa. Detalle que evita sorpresas: **al reanudar, el nodo se re-ejecuta desde el principio**, y `interrupt` devuelve entonces el valor de la reanudación — el trabajo previo a la pausa debe ser barato e idempotente; lo caro vive después.

## Automatizar todo o poner una puerta

El trade-off es de criterio, no técnico. Automatizar todo falla donde el sistema no tiene información para decidir bien (una estimación floja que sale como si fuera sólida es un problema de negocio). Una puerta en cada paso falla por el lado opuesto: convierte un flujo rápido en una cola de aprobaciones y quema a quien aprueba. **La regla es proporcional al coste del error:** lo transitorio y lo degradable se resuelve solo; la puerta humana se reserva para el punto donde el coste de equivocarse es alto y el sistema no tiene certeza. Una puerta, en el sitio crítico — no diez repartidas por el flujo.

---

# Parte 6 — Observabilidad: LangSmith y Logfire para el servicio IA

## Qué es observar un flujo agéntico

Todo lo anterior comparte un supuesto: que puedes ver la ejecución por dentro. La unidad es el **span** — un tramo con nombre, inicio, fin y atributos —; los spans se organizan en un árbol, la **traza**, que refleja las relaciones padre/hijo (petición → ejecución del grafo → cada nodo → llamada al modelo o consulta a la base). Sobre esa estructura se calculan las métricas que importan: latencia por nodo, tasa de éxito por nodo, coste por ejecución. Un grafo se presta especialmente bien a esto porque los nodos ya son las unidades naturales de medida.

## Dos herramientas, dos filosofías

**LangSmith** (LangChain) es una plataforma de trazabilidad, evaluación y depuración pensada para agentes; traza el grafo de forma nativa como árbol navegable, añade evaluación como ciudadano de primera clase. Se activa casi solo con variables de entorno; su encaje más natural es dentro del ecosistema LangChain. **Logfire** (Pydantic) es observabilidad construida sobre **OpenTelemetry**; su rasgo distintivo es que no observa solo la capa del modelo, observa **toda la aplicación** — instrumenta FastAPI, asyncpg y el cliente HTTP con una línea cada uno, y expone los spans por SQL (las métricas son consultas, no un cuadro de mando cerrado).

## Full-stack frente a solo-LLM: el criterio que decide

Las herramientas centradas en LLM ven muy bien la capa del modelo, pero cuando un nodo llama a una herramienta que consulta la base vectorial, ven la llamada y el resultado — **lo que pasó en medio es una caja negra**. En un servicio construido sobre FastAPI + asyncpg + Postgres, buena parte de los problemas viven justo en esa costura: una recuperación lenta porque la consulta tarda de más, un timeout que en realidad es un problema de conexión, una estimación cara porque se repitió trabajo. Una herramienta solo-LLM no distingue si el problema está en la IA o en la infraestructura; Logfire, al trazar toda la petición sobre OpenTelemetry, sí. **Para un servicio full-stack con base de datos, la elección de referencia es Logfire; LangSmith es la natural cuando el proyecto vive dentro de LangChain.** No es que una sea mejor — ven cosas distintas.

> La pregunta de si la orquestación formal se ganaba su sitio deja de responderse por fe en la abstracción: se responde con la traza delante. Un sistema que se ve es un sistema que se puede mejorar; el resto es iterar con datos.

---

# Chuleta de una página

| Concepto | Qué es / resuelve | Cuándo SÍ | Cuándo NO | Coste / palanca |
|---|---|---|---|---|
| **Bucle a mano** | `while` + function calling, tú escribes las ramas | Agente único, iterativo, forma simple | Pasos con dependencias, ramas reales, paralelismo | Cero diseño previo, se lee de un tirón |
| **`StateGraph`** | Grafo explícito: estado + nodos + aristas | El flujo tiene forma de grafo de verdad | Una llamada, o un agente ReAct de bucle único | Diseño previo del esquema de estado |
| **Reducer** | Cómo se combina cada actualización | Sobrescritura (último valor) o acumulación (`operator.add`) | — (siempre hay que declarar uno) | Habilita el fan-in bajo paralelismo |
| **Checkpointer** | Persiste el estado tras cada nodo | Flujos que deben sobrevivir a un reinicio | Prototipo desechable, tests | `AsyncPostgresSaver` sobre el Postgres que ya tienes |
| **Memoria corta vs larga** | Estado de ejecución vs historial de negocio | Corta: reanudar/inspeccionar. Larga: contexto futuro | No mezclar checkpointer con base de negocio | Dos problemas, dos almacenes |
| **Send API (fan-out)** | Paraleliza trabajo independiente por elemento | Componentes/búsquedas sin dependencia entre sí | Pasos dependientes entre sí | `operator.add` para el fan-in |
| **Arista condicional** | Lee el estado, decide el siguiente nodo | Puntos de decisión reales | Cada transición (pierde claridad) | Función pura, sin llamada al modelo |
| **Ciclo acotado** | Vuelve atrás con tope explícito | Reintento/replanificación acotada | Ciclo sin contador propio | `recursion_limit` es la red, no la estrategia |
| **`RetryPolicy` / fallback** | Reintento con backoff / camino alternativo | Fallo transitorio / dependencia caída persistente | Baja confianza (eso es `interrupt`) | Backoff automático del framework |
| **`interrupt`** | Pausa, persiste, espera decisión humana | Alto coste de error + baja certeza | Todo lo que se resuelve solo | Necesita checkpointer; nodo idempotente |
| **Span / traza** | Mide un tramo de ejecución | Siempre en producción | — | Latencia, éxito y coste por nodo |
| **Logfire vs LangSmith** | Full-stack (OpenTelemetry) vs solo-LLM (LangChain) | Logfire: stack FastAPI+DB. LangSmith: ecosistema LangChain | — | Ver la costura donde vive el problema real |

**La meta-lección, otra vez:** ningún framework sustituye la ingeniería del bucle a mano — la hace explícita cuando la forma del problema lo justifica. Empieza siempre por lo más simple que pase tus pruebas. Sube de bucle a grafo, de secuencial a paralelo, de silencioso a observable, **solo cuando la forma o el coste te obliguen**, y mide la línea base antes de decidir cada paso.

---

## Cómo conecta con nuestro ejercicio

- **`langgraph` está instalado pero no se usa.** Aparece en `uv.lock` como dependencia transitiva (arrastrada por otra librería), no en `pyproject.toml`, y no hay ni un `import langgraph`, `StateGraph` ni `checkpointer` en el código fuente. La brecha de S13 es literal: el paquete existe en el entorno, el grafo no existe en el sistema.
- **El bucle de S12 (`app/generation/agentic/agent_loop.py`) es exactamente el "bucle a mano" de la Parte 1, y hoy es secuencial donde el artículo de paralelismo pide fan-out.** `run_task_hours_recovery_agent` es un `while True` plano con `for call in calls:` que despacha cada `function_call` **una a una**, sin `asyncio.gather` — aunque el modelo emita varias llamadas paralelas en un mismo turno (el propio artículo de S12 ya avisaba de esto), el código actual las ejecuta en fila. Es el caso de manual de la Parte 4: `search_budgets` por componente es trabajo independiente, candidato directo a Send API si se reexpresa como grafo.
- **El pipeline RAG (`app/generation/rag/estimator.py`) es casi literalmente el ejemplo trabajado en la Parte 2.** Sus etapas fijas — retrieval (con corte temprano si falla) → generación → validación (con un reintento correctivo) → chequeo de coherencia → caché opcional — calcan la forma de cinco nodos con responsabilidad propia y una arista condicional en la validación que el artículo usa como ejemplo canónico de "esto sí tiene forma de grafo".
- **El Boss/Critic (`boss.py`/`critic.py`) ya es un bucle con estado y ramas fijas, pero por los propios criterios de la Parte 1 no pide grafo todavía.** `Boss.run` es un `for iteration in range(max_iterations)` con `_decide` bifurcando a `accept`/`synthesize`/`iterate` — el código lo llama "una pequeña máquina de estados" en un comentario, pero es un agente único iterando, sin dependencias entre pasos ni paralelismo real. Según la regla práctica de la Parte 1 ("agente único que razona en bucle → el bucle a mano ya es una respuesta profesional"), esto se queda como está; no es la pieza que justifica LangGraph.
- **La infraestructura para el checkpointer ya está puesta.** El proyecto ya tiene `asyncpg` + `pgvector` sobre el mismo Postgres (además de `psycopg` síncrono para Alembic/repos), que es exactamente el stack que la Parte 3 señala como el que casa con `AsyncPostgresSaver` — reutilizando la base existente, sin infraestructura nueva.
- **No hay ningún campo de estado tipo `needs_review` o `interrupt` en el dominio.** `app/domain/agent_estimation.py` y `app/domain/schemas/agent_trace.py` no modelan una parada explícita; la revisión humana existe hoy como un paso manual fuera de banda en el wizard (el humano edita el árbol entre la fase 1 y la fase 2 del agente), no como un `status` que el propio flujo produzca. Es la brecha concreta de la Parte 5: el sistema ya "sabe" que a veces hace falta un humano, pero no lo expresa como dato.
- **Hay retries puntuales, pero no una estrategia por tipo de fallo ni circuit breaker.** `critic.py` tiene `max_retries=3` en su llamada estructurada, `estimator.py` hace un reintento correctivo de citas, e `idempotency.py` cubre reintentos seguros del lado cliente — pero es ad hoc por sitio, no la matriz de la Parte 5 (transitorio → backoff, dependencia caída → fallback/circuit breaker, excepción → reanudación). No hay circuit breaker en ningún punto del código.
- **La observabilidad actual (`observability.py`) ya tiene la forma correcta, pero le falta la costura de infraestructura que pide la Parte 6.** `log_stage` es un context manager (structlog) que emite `stage.started`/`stage.completed` con `duration_ms` y `stage.failed`, correlado por `request_id` — conceptualmente ya son spans por etapa. Pero no hay `opentelemetry`, `logfire` ni `langsmith` en ningún sitio: no se traza la consulta a Postgres ni la llamada HTTP subyacente, exactamente la caja negra que el artículo describe para las herramientas "solo-LLM". Dado que el stack es FastAPI + asyncpg + Postgres (full-stack, no solo LangChain), Logfire es la elección que el propio artículo recomendaría aquí.
- **440 tests recogidos hoy** (`uv run pytest --collect-only -q`), sobre la base de S12 (420 tests). Ninguno ejercita `langgraph`, paralelismo real de tools, checkpointers ni spans de infraestructura — si se porta cualquier pieza de S13, esa cobertura nace de cero.
