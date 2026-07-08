# Sesión 12 — Agentes: el bucle, las tools y su coste (versión clara)

> Versión simplificada del resumen de los 6 artículos de la Sesión 12.
> Misma información, menos paja. Cada término técnico se explica en una frase.
> **Hilo conductor:** el mismo de siempre — un sistema que, a partir de la transcripción de una reunión, produce una estimación estructurada de un proyecto software. La Sesión 9 lo hizo recuperar; la 10, recuperar bien; la 11 se ocupó de generar de forma confiable. Todo eso era un **pipeline fijo**: pasos que tú escribes, siempre en el mismo orden. La Sesión 12 se pregunta qué pasa cuando la transcripción es tan variable que ningún orden fijo sirve — y la respuesta es dejar que **el modelo decida el siguiente paso**. Eso es un agente. La sesión entera consiste en desmitificarlo: qué es (un bucle), cuándo vale la pena (casi nunca), cómo se construye (cincuenta líneas), y cuánto cuesta (medible hasta el token).

---

## Glosario base (léelo una vez y vuelve cuando haga falta)

| Término | Qué es, en una frase |
|---|---|
| **Pipeline** | Secuencia de pasos que tú escribes; el modelo rellena cada hueco pero no decide el orden. Predecible, barato, testeable. |
| **Tarea / Workflow / Agente** | Escala de autonomía: una llamada (tarea) → varias llamadas encadenadas por ti (workflow) → el modelo dirige su propio proceso (agente). |
| **Agente** | Un bucle en el que el modelo elige la siguiente acción a partir de lo que observa, y sigue hasta que considera que ha terminado. |
| **Bucle agéntico (ReAct)** | Razonar → actuar → observar → repetir, hasta una respuesta final o un límite. La formulación canónica es ReAct (Yao et al.). |
| **Function calling / tool use** | Mecanismo por el que el modelo **pide** ejecutar una función (no la ejecuta él); tu código la corre y le devuelve el resultado. |
| **Tool** | Una capacidad ejecutable expuesta al modelo como función invocable: nombre, descripción, parámetros (JSON Schema) y su ejecución real. |
| **Schema estricto (`strict: true`)** | Garantía de que los argumentos que genera el modelo se ciñen exactamente al JSON Schema declarado. Valida forma, no sentido. |
| **Observación** | Lo que devuelves al modelo tras ejecutar una acción; su ground truth del entorno en cada paso. Un error informativo también es observación. |
| **Estado / traza** | El contexto que se acumula vuelta a vuelta (decisión + observación); es a la vez memoria del bucle y registro para depurar. |
| **Handover** | Transferencia de control: hacia un humano (human-in-the-loop) o hacia otro agente, con un contrato explícito de qué estado pasa. |
| **Condición de parada** | La guarda del bucle: respuesta final, `MAX_STEPS`, o presupuesto agotado. Sin ella, un agente confundido quema tu cuota. |
| **Enrutado (routing)** | Un clasificador barato al principio que manda lo simple al pipeline y lo complejo al agente, para pagar la autonomía solo cuando hace falta. |
| **Tokens de razonamiento** | Tokens internos que un modelo de razonamiento gasta deliberando antes de responder; se facturan como tokens de salida. |
| **Ledger de coste** | Un pequeño libro de cuentas que acumula el `usage` (tokens) de cada llamada del bucle para saber qué costó cada ejecución. |
| **Reactivo / proactivo** | Decidir solo a la luz de la última observación (reactivo) o anticipar un plan hacia el objetivo (proactivo). |

---

## La idea en una página

El pipeline de las sesiones anteriores funciona, es barato y falla de formas que sabes anticipar. **Un agente no es una mejora gratuita del pipeline: es una decisión arquitectónica con un coste concreto, y casi siempre la respuesta correcta es no añadirlo.** La sesión monta el argumento entero alrededor de una sola pregunta —cuándo *sí*— y luego enseña a construirlo y a pagarlo sin sorpresas.

| # | El tema | El artículo |
|---|---------|-------------|
| 1 | **¿Cuándo dejar de escribir tú los pasos?** El pipeline se rompe cuando el problema no tiene forma conocida de antemano: no sabes cuántos componentes hay ni en qué orden atacarlos hasta leer la transcripción. | **De pipeline a agente** (Parte 1) |
| 2 | **¿Qué pasa dentro de una vuelta del bucle?** Razonamiento, planificación, acción, observación, handover y estado — nombrar los órganos es lo que te deja depurarlos. | **Anatomía de un agente** (Parte 2) |
| 3 | **¿Cómo pasa el modelo de hablar a actuar?** Function calling: el modelo pide, tú ejecutas. Una interfaz tipada con un cliente inusual. | **Function calling en la práctica** (Parte 3) |
| 4 | **¿Cómo se construye de verdad?** Un agente funcional cabe en ~50 líneas: bucle + registro de tools + system prompt + esquema de salida. Sin frameworks. | **El bucle agéntico paso a paso** (Parte 4) |
| 5 | **¿Qué forma darle, y cómo hacer que use bien sus tools?** Los ejes (un paso/iterativo, reactivo/proactivo, plan fijo/dinámico) y la palanca real: el diseño de las tools. | **Patrones de agentes y diseño de tools** (Parte 5) |
| 6 | **¿Cuánto cuesta, y de dónde sale el sobrecoste?** El contexto que engorda vuelta a vuelta domina la factura. Medible hasta el token, controlable con ingeniería corriente. | **Cuánto cuesta un agente** (Parte 6) |

> **El hilo que atraviesa las seis partes:** un agente no es un paradigma nuevo que jubila tu ingeniería de software. Es **una decisión de control de flujo** — en lugar de escribir tú el `if/else` que elige el siguiente paso, el modelo emite la siguiente acción y tú la ejecutas en un bucle. Esa línea es toda la novedad, y está acotada. Todo lo que la rodea —tools y contratos, validación, observabilidad, control de coste, condición de parada— es ingeniería que ya sabes hacer. La parte difícil no es construir el agente; es resistir la tentación de meterlo donde un workflow habría hecho el trabajo mejor, más barato y con menos sorpresas.

---

# Parte 1 — De pipeline a agente: cuándo tu sistema necesita una capa de decisión

## El pipeline que ya funciona

Conviene ser honestos sobre lo bueno que es un pipeline fijo, porque el marketing de agentes tiende a hacérnoslo olvidar. Un pipeline es una secuencia de pasos que **tú** escribes:

```python
def estimate_from_transcript(transcript: str) -> Estimate:
    query = reformulate(transcript)
    budgets = search_budgets(query)
    return generate_estimate(transcript, budgets)
```

El control de flujo es tuyo. El modelo rellena cada hueco, pero no decide la estructura. Y eso trae cuatro propiedades muy deseables: es **predecible** (misma entrada, mismo camino; si algo falla sabes en qué paso), **barato** (sabes cuántas llamadas al LLM haces por petición), **testeable** (cada paso por separado, con aserciones deterministas) y **rápido** (sin negociación con el modelo sobre qué hacer a continuación). Para una parte enorme de los problemas reales —clasificar, extraer campos, una recuperación seguida de una generación— esto es todo lo que necesitas. **El pipeline es el estado por defecto.** La pregunta es qué tiene que romperse para justificar salir de él.

## El punto en el que el pipeline se rompe

Dos transcripciones. La primera: *"una landing page con formulario de contacto y despliegue en un hosting sencillo"*. Un componente, una búsqueda, una estimación. El pipeline lo clava — la forma del problema es fija y tú ya la codificaste. La segunda: un kickoff real con un portal de clientes, una integración con el ERP del cliente vía API, una app móvil que consume el portal, y una migración de datos de un legacy que *"nadie sabe muy bien cómo está montado"*.

Aquí el pipeline cruje, y merece la pena ver por qué. **El problema no tiene una forma conocida de antemano:** no sabes cuántos componentes hay hasta leer la transcripción, ni cuántas búsquedas necesitas, ni en qué orden conviene atacarlas, ni si estimar la migración cambia cómo estimas la integración. Dentro del paradigma del pipeline solo tienes dos malas salidas: (1) una única búsqueda gigante que devuelve un revoltijo de presupuestos incomparables y hunde la calidad, o (2) un árbol de decisiones codificado a mano —"si hay integración, esta rama; si hay migración, esta otra"— que no escala porque cada cliente trae una combinación nueva. Lo que falta no es más recuperación ni mejor generación: es **capacidad de decisión en tiempo de ejecución**.

## Tres niveles: tarea, workflow y agente

Ayuda un vocabulario preciso, porque "agente" se usa para casi todo. Anthropic y Barry Zhang proponen una escala de tres niveles:

- **Tarea.** Una única llamada al modelo. Resume, clasifica, extrae. Coste predecible, fallos acotados.
- **Workflow.** Varias llamadas encadenadas en un flujo de control que **tú** defines. Reformular → recuperar → generar es un workflow. Aquí vive la mayor parte de un sistema RAG bien hecho.
- **Agente.** El modelo dirige su propio proceso: decide la siguiente acción a partir de lo que observa, y sigue hasta que considera que ha terminado. Tú posees el objetivo y las barreras de seguridad; no posees cada rama del camino.

> La frase que mejor lo resume (Zhang): con un workflow, la fontanería la controlas tú; con un agente, la fontanería la controla el modelo. Todo lo demás —coste, latencia, testabilidad, observabilidad— se deriva de esa única diferencia estructural.

Desde el código, un agente es un bucle:

```python
def run_agent(transcript: str) -> Estimate:
    messages = build_initial_context(transcript)
    for _ in range(MAX_STEPS):
        decision = model.decide(messages, tools=TOOLS)
        if decision.is_final():
            return decision.estimate
        observation = execute_tool(decision.tool_call)
        messages.append(observation)
    raise AgentDidNotConverge()
```

La diferencia con el workflow no es el bucle —los bucles no tienen nada de nuevo—. Es la línea `model.decide`: **quién elige el siguiente paso.** En el workflow lo elegiste tú al escribir la secuencia; en el agente lo elige el modelo en cada vuelta. Esa es toda la novedad; el resto es control de flujo de cualquier programa.

## Qué compra realmente un agente

Una sola cosa: **la capacidad de resolver problemas cuyo árbol de decisión no puedes pre-mapear.** El agente lee la transcripción compleja, decide que hay cuatro componentes con perfiles distintos, trata cada uno como sub-tarea (busca presupuestos para el ERP por un lado, la migración por otro), calcula parciales y consolida; y si una búsqueda devuelve poco, reformula y reintenta antes de calcular sobre datos malos. Ese camino no lo escribiste tú: lo construyó el modelo al vuelo.

Fíjate en lo que **no** compras: no compras mejor recuperación (busca con las mismas tools), ni mejor generación (consolida con el mismo modelo), ni inteligencia nueva. Compras **exclusivamente orquestación adaptativa**. Si tu problema tiene forma fija, no hay nada aquí para ti.

## El precio de la autonomía

Aquí el marketing suele callarse:

- **Latencia.** Cada vuelta es una ida y vuelta al modelo. El pipeline hacía una o dos llamadas; el agente puede hacer ocho. Dos segundos pasan a veinte.
- **Coste.** La exploración cuesta tokens. Regla mental (Zhang): ~10 céntimos de dólar por tarea ≈ 30–50 mil tokens. Un agente multiplica por varias veces lo del pipeline. A escala —un millón de peticiones al mes gastando 5× de más— eso es del orden de **millón y medio de dólares al año** de más.
- **No-determinismo.** La misma entrada puede recorrer caminos distintos. Complica el testing y hace de reproducir un bug un ejercicio de paciencia.
- **Los errores se componen.** En un pipeline, una recuperación mala produce una respuesta mala: un fallo acotado. En un agente, una recuperación mala en el paso dos puede convertirse en tres pasos más construidos sobre esa base podrida. La autonomía amplifica aciertos y errores.
- **Deuda de observabilidad.** Ya no basta loguear entrada/salida: necesitas trazar decisiones —qué razonó, qué tool eligió, qué observó, por qué siguió—.

## Los criterios de decisión

Traducido a preguntas concretas ante un problema real:

1. **¿Puedes pre-mapear el árbol de decisión?** Si puedes enumerar pasos y ramas, constrúyelo como workflow. Que puedas mapearlo es la señal más fuerte de que no necesitas agencia.
2. **¿El problema tiene forma variable?** Si número, orden o naturaleza de los pasos dependen de la entrada de formas que no puedes enumerar, es territorio de agente.
3. **¿El valor justifica el gasto?** Alto volumen / bajo valor por unidad (clasificar millones de tickets) → workflow. Bajo volumen / alto valor (estimar un proyecto de seis cifras) → puede justificar el sobrecoste.
4. **¿Cuál es el coste del error, y puedes verificarlo?** Si un error es caro y difícil de detectar, la autonomía es un pasivo. Mitiga con tools de solo lectura, validación automática de la salida, y humano en el bucle en los puntos críticos.
5. **¿El modelo es bueno en tu dominio?** Sobre un modelo que no domina el dominio, la agencia solo produce fallos más elaborados.

> El caso que cumple las cuatro condiciones a la perfección son los **agentes de código**: problema ambiguo, valor obvio, modelos buenos en ello, y —clave— resultado verificable con tests. Cuando tu problema las cumple, el agente se gana su sitio. Cuando no, sospecha.

## Cómo se aplica a nuestro sistema

La conclusión no es "reemplaza el pipeline por un agente". Es una **arquitectura de dos vías**: el pipeline sigue siendo el camino por defecto (las transcripciones simples, que son la mayoría, lo recorren tal cual), y el agente entra como una **capa de decisión por encima**, no como sustituto. El detalle que lo hace limpio: **las piezas del pipeline se convierten en las tools del agente.** La recuperación pasa a ser `search_budgets`; el cálculo, `calculate_estimate`; la validación, `validate_estimate`. No reimplementas nada — promocionas los pasos del workflow a acciones invocables. Un clasificador ligero al principio decide simple→pipeline o complejo→agente. Y todo esto vive **dentro del servicio IA**: el backend de negocio sigue enviando una transcripción y recibiendo una estimación por el mismo contrato de siempre, le da igual si detrás hubo tres pasos u ocho llamadas.

---

# Parte 2 — Anatomía de un agente: qué ocurre dentro del bucle

"Un bucle" es cierto pero no te dice nada sobre lo que pasa dentro de cada vuelta, y ahí es donde se gana o se pierde el control. Nombrar las partes no es taxonomía: es exactamente lo que te permite depurar, medir el coste y decidir dónde intervenir. **No puedes depurar lo que no sabes nombrar.**

## El esqueleto: reason, act, observe, repeat

La formulación canónica viene de **ReAct** (Yao et al.): el modelo intercala trazas de razonamiento y acciones. Razonar sin actuar se queda sin datos frescos y alucina; actuar sin razonar no sabe qué hacer con lo que trae. En su forma original era prompting explícito:

```
Thought: The transcript describes two independent components; I will estimate each.
Action: search_budgets(query="ERP integration REST")
Observation: 4 historical budgets found; median 120h for a similar integration.
Thought: The migration component has no clear match; I need to reformulate.
Action: search_budgets(query="legacy data migration undocumented schema")
Observation: 1 weak match; low confidence.
```

Ese patrón `Thought / Action / Observation` en bucle es el esqueleto; el resto son los órganos que cuelgan de él. Un detalle que cambia cómo se construye hoy: **con los modelos de razonamiento actuales, buena parte del `Thought` ya no la escribes tú; ocurre de forma nativa dentro del modelo.** Y el esqueleto necesita una **condición de parada** — respuesta final, máximo de pasos, o presupuesto de error agotado. Un bucle sin guarda es un bug esperando a pasar.

## Razonamiento: decidir qué hacer

Es la facultad de interpretar la situación y elegir la siguiente acción. El matiz que separa el modelo mental de la implementación real: ReAct nació con el razonamiento explícito en texto (podías leerlo); los modelos actuales lo hacen nativamente, gastando **tokens internos de razonamiento** que no escribes ni ves. No desaparece el `Thought`: se muda dentro del modelo. La consecuencia es doble — ya no tienes que enseñarle a razonar con ejemplos, pero pierdes el control fino sobre esa traza. Para auditabilidad estricta hay que capturar deliberadamente los **reasoning summaries** que algunos proveedores exponen; por defecto, el razonamiento es opaco.

## Planificación: descomponer el problema

Si el razonamiento decide el siguiente paso, la planificación decide la forma del conjunto. Dos momentos posibles, con implicaciones distintas: el **plan por adelantado** (el agente esboza los pasos al principio y luego los ejecuta — más auditable, más rígido) y la **planificación continua** (decide el siguiente paso en cada vuelta — se adapta, pero es más difícil de anticipar y presupuestar). Con modelos capaces, la planificación tiende a ser **emergente**. Nombrarla como componente te da una palanca: cuando necesitas justificar ante un cliente por qué la estimación salió como salió, puedes **forzar** un plan explícito como primer paso y guardarlo. Forzarlo o dejarlo emerger es una decisión de diseño, no un detalle del modelo.

## Acción: tocar el mundo

Es el único punto en el que el agente afecta a algo fuera de sí mismo. Mecánicamente es function calling, y su contrato es el de una interfaz tipada de toda la vida: tú declaras qué operaciones existen y qué forma tienen; el modelo emite una petición estructurada; tu código la ejecuta y devuelve el resultado. **El modelo nunca ejecuta nada por su cuenta** — emite una intención y tú decides qué hacer con ella. Esa mediación tuya es donde vive la seguridad del agente, y conviene no regalarla: `search_budgets` es de solo lectura (reversible, segura de conceder); una acción que escribe en producción, envía un correo o mueve dinero es otra cosa. Principio de **mínimo privilegio**: das las acciones que necesita y ni una más, y las irreversibles pasan por una comprobación —o por un humano— antes de ejecutarse.

## Observación: leer la respuesta del entorno

Es lo que devuelves al modelo tras ejecutar una acción, su ground truth en cada paso. Sin observación, el modelo razona sobre su propia imaginación. Lo que se subestima es cuánto **la calidad de la observación gobierna la calidad de la siguiente decisión**: una observación estructurada y concreta (identificadores estables, solo los campos necesarios) alimenta buen razonamiento; una inflada —doscientos ítems en crudo cuando bastaban cinco— desperdicia contexto y confunde. **Los errores son un caso especial de observación, y el más importante:** si `search_budgets` no encuentra nada y se lo devuelves con información ("1 coincidencia débil, baja confianza para migración legacy"), el agente puede razonar y reformular; si se lo devuelves como un genérico "error" o lo ocultas, se queda ciego y da tumbos. Un error informativo es lo que permite a un agente recuperarse de sus propios fallos.

## Handover: saber cuándo apartarse

Un agente no siempre debe terminar el trabajo solo. El handover es la transferencia de control, en dos direcciones. **Hacia un humano** (human-in-the-loop): el agente se detiene y pide criterio, o escala cuando su confianza es baja o la acción es cara e irreversible. Si el componente de migración legacy no tiene ninguna referencia histórica fiable, el agente puede estimar el resto con solvencia y, para esa pieza, marcarla como necesitada de revisión humana en lugar de inventar un número con falsa precisión — eso no es un fallo, es un agente bien diseñado reconociendo su límite. **Hacia otro agente:** delegar una sub-tarea a un especialista (la base de las arquitecturas multi-agente). En ambos casos el handover necesita un **contrato explícito**: qué estado se transfiere, quién pasa a ser dueño de la decisión, y cómo vuelve el control. En nuestro sistema se traduce limpiamente: el servicio IA devuelve un estado (`needs_review`) con lo que sí calculó y la razón, y el backend lo enruta:

```ruby
result = ai_service.estimate(transcript)
case result.status
when "done"          then save_estimate(result.estimate)
when "needs_review"  then enqueue_for_human_review(result.partial_estimate, result.reason)
end
```

El handover deja de ser abstracto: es un `status` en una respuesta y un `case` que lo enruta. Software normal.

## El estado: el órgano que engorda

El bucle no es memoria pura del modelo: es una estructura que **tú** mantienes y que crece en cada vuelta con la decisión y su observación. Ese estado acumulado **es** la traza —lo que puedes loguear, inspeccionar y depurar—. Pero tiene un coste que es la contrapartida directa de la anatomía: cada vuelta añade al contexto, y ese contexto se **reenvía** al modelo en la siguiente. El bucle no solo hace más llamadas; **cada llamada es más cara que la anterior**, porque arrastra todo lo observado. Un agente en su octava vuelta paga por reenviar las siete observaciones previas. En agentes largos acabas necesitando adelgazar el estado —resumir observaciones viejas, descartar las que ya no informan, quedarte con el identificador en lugar del contenido—. No es optimización prematura: es la consecuencia estructural de un bucle que acumula.

> **La anatomía desmitifica:** el razonamiento es lógica de decisión (ahora dentro del modelo, no en tus `if/else`); la planificación es descomposición de un problema; la acción es una llamada a función con efectos; la observación es un valor de retorno que vuelves a meter en el flujo; el handover es escalado y delegación; y el bucle es control de flujo con una guarda. Un agente cuyos órganos sabes nombrar es un sistema que puedes operar; uno cuyos órganos no distingues es una caja negra a la que solo puedes rezarle.

---

# Parte 3 — Function calling en la práctica: tools, schemas y contrato con el modelo

Empecemos matando el malentendido de raíz, porque contamina todo lo demás: **el modelo no ejecuta tu código. Nunca.** Ni consulta tu base de datos, ni corre tu función de cálculo. Lo único que hace es emitir una petición estructurada —"quiero llamar a `search_budgets` con estos argumentos"— y tu código decide qué hacer con ella. Function calling no es el modelo ejecutando funciones; es el modelo **pidiéndote** que las ejecutes tú.

## El contrato: cuatro tiempos

1. **Tú declaras** las tools disponibles: qué operaciones existen y qué forma tienen sus entradas.
2. **El modelo**, si decide que necesita una, emite una petición estructurada con nombre y argumentos.
3. **Tu código ejecuta** la operación — aquí es donde de verdad se consulta la base vectorial o se corre el cálculo.
4. **Devuelves el resultado** al modelo, que continúa razonando con ese dato nuevo.

Visto así no es exótico: es una interfaz tipada de manual. La única diferencia con cualquier API que hayas integrado es **quién está al otro lado pidiendo** — un modelo que elige la función según la conversación, en lugar de un cliente con un flujo fijo.

## Anatomía de una tool: nombre, descripción, parámetros, schema

El modelo solo ve esto —nunca tu implementación—, así que trátalo con respeto:

- **Nombre.** Identificador único. Cuando la biblioteca crece, un namespace desambigua (`budgets_search`, `estimate_calculate`).
- **Descripción.** Lo que el modelo lee para decidir cuándo y cómo usar la tool. **La pieza de mayor apalancamiento.**
- **Parámetros.** JSON Schema: tipos, campos requeridos, enums, y una descripción por parámetro.
- **Schema estricto** (`strict: true`). Los argumentos se ciñen exactamente al schema declarado.

```python
TOOLS = [{
    "type": "function",
    "name": "search_budgets",
    "description": (
        "Search historical project budgets for one software component. "
        "Call this once per component; do NOT combine unrelated components "
        "(for example, an ERP integration and a data migration) into one query."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "A focused description of one component."},
            "component_type": {"type": "string", "enum": ["integration", "migration", "frontend", "backend"]},
        },
        "required": ["query", "component_type"],
        "additionalProperties": False,
    },
    "strict": True,
}]
```

Fíjate en cuánta intención hay en la descripción y los enums. **No están para documentar: están para dirigir el comportamiento.** El enum restringe lo que el modelo puede pasar; la instrucción "una llamada por componente" evita que meta integración y migración en una sola búsqueda y reciba un revoltijo inútil. El schema no solo valida: **enseña.**

## El ida y vuelta (Responses API de OpenAI)

```python
response = client.responses.create(model="gpt-5", reasoning={"effort": "medium"},
                                    input=[{"role": "user", "content": transcript}], tools=TOOLS)
for item in response.output:
    if item.type == "function_call":
        args = json.loads(item.arguments)
        result = execute_tool(item.name, args)   # tu código
        response = client.responses.create(
            model="gpt-5", previous_response_id=response.id,
            input=[{"type": "function_call_output", "call_id": item.call_id, "output": json.dumps(result)}],
            tools=TOOLS)
```

Tres cosas que no pasar por alto: (1) la salida **no es texto**, es una lista de items tipados — recorre `response.output` e inspecciona cada `type`, no asumas que el primero es la respuesta; (2) cada `function_call` trae un **`call_id`**, y al devolver el resultado tienes que referenciar ese mismo id — olvidarlo es el error más común al empezar; (3) el estado se encadena con **`previous_response_id`**, así el modelo mantiene el contexto sin reenviarlo a mano. Un aviso que ahorra una hora de depuración: en la Responses API el schema es **plano** (`type`, `name`, `description`, `parameters` al mismo nivel); en Chat Completions va anidado bajo `function`. Copiar el formato de una a otra da un error de parámetro poco obvio.

## Llamadas en paralelo

Una misma respuesta puede contener **varias** `function_call`. Es deseable: ante cuatro componentes independientes, el modelo puede pedir cuatro `search_budgets` de golpe. Recoge **todas**, ejecútalas concurrentemente (`asyncio.gather`, ya que las tools son asíncronas) y devuelve **todos** los `function_call_output` —cada uno con su `call_id`— en **una única** petición de continuación. Dar por hecho que siempre hay exactamente una es un bug clásico: funciona con transcripciones simples y se rompe con la primera reunión compleja.

## El mismo contrato en otro proveedor

Function calling no es de OpenAI. En la API de Anthropic la tool se declara con `input_schema` (no `parameters`), el modelo devuelve bloques `tool_use` (no items `function_call`), llega con `stop_reason: "tool_use"`, y contestas con un bloque `tool_result`. **Los nombres cambian; el contrato es idéntico.** Consecuencia arquitectónica que conviene aprovechar: aísla esas diferencias de transporte en una capa fina (o delégalas en un agregador) y mantén la lógica de tus tools independiente del proveedor.

## Diseñar tools que el modelo use bien

La mecánica es fácil; que el modelo las use bien es el trabajo real, y se reduce a dos superficies: **la descripción** (gobierna la entrada) y **el resultado** (gobierna la siguiente decisión).

- **La descripción es la interfaz.** Si el modelo escoge la tool equivocada o inventa argumentos raros, la causa casi nunca es el modelo: es una descripción vaga. Escríbela para un lector que no ve tu código.
- **Resultados de alto valor.** Devuelve solo lo necesario para decidir el siguiente paso, con identificadores estables — no un volcado de doscientas filas. Un resultado inflado desperdicia contexto (que reenvías cada vuelta) y confunde.
- **Los errores también son resultados.** Informativos, no un genérico "error".
- **Valida los argumentos antes de lo que duele.** `strict: true` garantiza forma, no sentido. Para solo-lectura, ejecutar directo es aceptable; para acciones con efectos, añade tu capa de validación.
- **Cuida la granularidad.** Demasiadas tools con contornos solapados → el modelo duda; muy pocas y genéricas → hace malabares con argumentos. Punto dulce: una tool por operación con límites nítidos. Si te descubres explicando en la descripción *cuándo no* usar una tool, quizá esa tool hace demasiado.

> Function calling se revela como lo que es: una interfaz tipada cuyo cliente resulta ser un modelo. Lo único genuinamente nuevo es que quien elige la función y rellena sus argumentos es el modelo, a partir de una descripción en lenguaje natural. **La fiabilidad de tus tools no vive en un modelo mejor; vive en descripciones y resultados mejores.** Eso es ingeniería de interfaces, no aprendizaje automático.

---

# Parte 4 — El bucle agéntico paso a paso

Vamos a construir el agente **a mano**, sin frameworks — no porque los frameworks sean malos, sino porque montar el bucle en crudo es la única forma de entender qué hacen por ti y de tomar el control cuando lo necesites. Un agente de estimación funcional cabe en **~50 líneas**.

## Las piezas: cuatro elementos, ni uno más

- **Tools:** las capacidades ejecutables. Tres, cada una envolviendo algo que el servicio IA ya sabe hacer (`search_budgets`, `calculate_estimate`, `validate_estimate`). El agente no reimplementa nada; solo orquesta.
- **Modelo:** el orquestador (`gpt-5`, esfuerzo de razonamiento medio). Lee la situación y decide qué tool usar.
- **Bucle:** el esqueleto. Llamar al modelo, ejecutar las tools que pida, devolverle los resultados, repetir, hasta la respuesta final o el límite de pasos.
- **Estado:** el contexto que se acumula vuelta a vuelta; también la traza inspeccionable.

## El registro de tools

Declarar el schema es la mitad; la otra es conectar cada nombre de tool con la función que lo ejecuta. Un **registro** que mapea nombre → función desacopla dos cosas que no deberían conocerse: qué tools existen y cómo funciona el bucle. Añadir una tool nueva es añadir un schema a `TOOLS` y una entrada al registro; el bucle no cambia ni una línea. Y el despacho lleva un `try/except`: si una tool falla, no revienta el agente — devuelve el error como **observación**, y el modelo puede leerlo, razonar y reformular. Es una decisión de diseño, no un detalle defensivo.

## El bucle (el corazón, más corto que su reputación)

La primera llamada arranca fuera del bucle con la transcripción. Luego, cada iteración:

1. Mira la salida del modelo y recoge todos los items `function_call`. Si no hay ninguno → el modelo produjo su respuesta final → `break`.
2. Si hay llamadas, ejecútalas **todas en paralelo** con `asyncio.gather` (asumir una sola es un bug clásico).
3. Devuelve todas las observaciones juntas, cada una con su `call_id`, en una única continuación. El estado se encadena con `previous_response_id`; reenvías, eso sí, las `instructions`, porque `previous_response_id` **no arrastra el system prompt**.
4. Cada acción con su observación se guarda en la traza — tu única ventana a lo que decidió el agente y por qué.

Y todo el bucle vive dentro de `range(MAX_STEPS)`; el `else` del `for` (que corre solo si termina sin `break`) captura el caso en que el agente no converge y corta con un estado explícito de error. **Un bucle de agente sin límite de pasos es una factura esperando a dispararse.**

## El agente en marcha

Ante una transcripción con una integración ERP y una migración legacy, la traza acumulada se lee paso a paso. **Lo interesante es el paso 3:** en el paso 2 la búsqueda de la migración devolvió una única coincidencia débil, y el agente **no calculó sobre ese dato pobre** — leyó la observación, reformuló la consulta con otros términos y volvió a buscar antes de seguir. Eso es exactamente lo que un pipeline fijo no puede hacer, y no lo programaste tú: emergió de que el modelo pudo ver el resultado de su propia acción y decidir en consecuencia.

## La salida final estructurada

Cuando el modelo deja de pedir tools, produce la estimación final — y aquí **no queremos texto libre**, queremos una estructura determinista. Todas las llamadas pasan un `text_format` (un modelo Pydantic) al que la respuesta debe ceñirse. Cuando el bucle sale por `break`, `response.output_parsed` ya es un `Estimate` validado. Este es el punto clave para la estabilidad: **el agente puede recorrer un camino distinto en cada ejecución —tres búsquedas o cinco, un reintento o ninguno— pero la forma de lo que devuelve es siempre la misma. La no-determinación vive dentro del bucle; el contrato de salida es determinista.**

## El agente detrás de un endpoint

El bucle vive en el servicio IA, detrás de un endpoint (unas pocas líneas en FastAPI). Desde el backend de negocio, invocarlo es una llamada HTTP corriente. **El backend no ve el bucle, ni las `function_call`, ni los `call_id`, ni cuántas vueltas dio** — envía una transcripción y recibe un `status` y una estimación estructurada. Esa frontera te permite reescribir por completo cómo el agente usa sus tools sin tocar una línea del backend.

## Qué te enseña construirlo a mano

- **El manejo de errores es tuyo,** y es donde se juega la robustez: el `try/except` convierte un fallo de tool en observación recuperable; `MAX_STEPS` impide el bucle infinito; el `status` de salida distingue éxito de agotamiento. Ninguna es opcional en producción.
- **La observabilidad no viene gratis.** La traza es tu instrumento de depuración; en un sistema real la enriqueces con tiempos por paso, tokens consumidos y el resumen de razonamiento.
- **Ahora entiendes lo que un framework haría por ti:** en buena medida te ofrece exactamente este bucle, más gestión de estado, reintentos, instrumentación y —en los más elaborados— orquestación como grafo. Puede que lo quieras, puede que no; la diferencia es que ahora es una decisión informada, no un acto de fe.

> Cincuenta líneas y ni una de magia: un bucle, un registro de tools, un system prompt y un esquema de salida. Mirar algo que suena a autonomía inteligente y reconocer, debajo, un `while` bien escrito con una condición de parada.

---

# Parte 5 — Patrones de agentes y diseño de tools de calidad

"Agente" no es una cosa. Un agente que da un solo paso y otro que itera veinte veces son animales diferentes, con costes, riesgos y modos de fallo diferentes. Dos mitades que se necesitan: **la forma** del agente, y **la palanca** que dirige su comportamiento dentro de esa forma — el diseño de las tools.

## Los tres ejes de la forma

- **Un solo paso o iterativo.** Un solo paso: una llamada, quizá una tool, y termina — casi un pipeline con una decisión; basta para lo simple. Iterativo: repite decidir/actuar/observar hasta converger — para problemas cuya forma no conoces de antemano. La decisión no es filosófica, es coste contra necesidad. **Si puedes resolverlo en un paso, hazlo en un paso.**
- **Reactivo o proactivo.** Reactivo: decide a la luz de lo que acaba de observar, sin plan hacia adelante — simple y sorprendentemente robusto (no se rompe cuando la realidad no encaja con un plan), pero puede ser miope. Proactivo: anticipa un plan hacia el objetivo — eficiente cuando el camino es predecible, frágil cuando no lo es. **Para nuestro caso la reactividad suele ganar** (las transcripciones traen sorpresas), con una pizca de proactividad: descomponer en componentes al principio.
- **Plan fijo o planificación dinámica.** Plan fijo: descompone al principio y ejecuta hasta el final — gran virtud, la **auditabilidad** (poder mostrar al cliente "el agente decidió estos cuatro componentes, en este orden, por estas razones"). Dinámica: re-planifica en cada vuelta según lo que observa — gana adaptabilidad, pierde previsibilidad.

> Los tres ejes **no son ortogonales:** un agente proactivo tiende al plan fijo; uno reactivo, a la planificación dinámica. No son tipos de catálogo, sino tres lentes para la misma decisión. Para el agente de estimación: **iterativo, mayoritariamente reactivo, con planificación ligera y dinámica** — una descomposición inicial floja, revisada sobre la marcha. Saber articular *por qué* es media batalla.

## Enrutar la forma según el caso

Una decisión que precede a todas las anteriores y se pasa por alto: **no tienes que elegir una sola forma para todas las entradas.** La mayoría de transcripciones son simples; comprometerte con el iterativo para todas significa pagar su coste también donde un solo paso resolvería mejor. Una clasificación barata y determinista al principio decide simple→un paso o complejo→iterativo. La pregunta deja de ser "qué forma tiene mi agente" y pasa a ser **"qué forma merece cada entrada"**.

## Las tools son la interfaz que dirige al agente

Fijada la forma, lo que determina que el agente decida bien son, casi por completo, las tools: cuáles existen y cómo las describes. El modelo lee nombres, descripciones y schemas — no tu código ni tu intención. Por eso el diseño de tools **no es documentación: es dirección de comportamiento.** De aquí un principio que ahorra muchísima depuración: **cuando el agente se comporta mal, casi siempre el fallo está en la descripción de una tool o en el conjunto de tools, no en el modelo ni en el bucle.** El modelo hizo lo que tus descripciones le dijeron; si te sorprende, es que decían algo distinto de lo que creías.

- **La descripción es un prompt que se itera.** Se escribe, se prueba, se observan resultados y se ajusta. Una versión ingenua ("Searches historical budgets.") no le dice al modelo que debe buscar un componente cada vez; la versión que arregla el comportamiento lleva **la restricción, el contraejemplo y la razón dentro de la propia descripción**. La diferencia entre un agente que estima bien y uno que produce números sin sentido vive enteramente en un campo de texto.
- **El conjunto de tools, no solo cada tool.** El modelo elige entre todas las que ofreces. Demasiadas con fronteras solapadas confunden; muy pocas y genéricas fuerzan malabares. Punto dulce: conjunto pequeño con fronteras nítidas. Señal de alarma: si te descubres explicando en una descripción cuándo *no* usar esa tool en favor de otra, las fronteras están mal trazadas — el arreglo no es una descripción más larga, sino un conjunto mejor delimitado.

## Optimizar es mirar las trazas

Nada de adivinar: coges un puñado de transcripciones representativas (simples, complejas, casos raros), ejecutas el agente, y **lees las trazas** — qué tool eligió, con qué argumentos, en qué orden, dónde se atascó. Cada anomalía se rastrea hasta una causa: descripción vaga, frontera mal puesta, resultado con demasiado ruido, o un error mudo que dejó al agente ciego. Ejemplo típico: el agente llama a `calculate_estimate` antes de haber buscado presupuestos para todos los componentes. El instinto es pensar que "se precipita"; la causa real es que la descripción no declara su **precondición**. Añades *"only call this after budgets have been searched for every component"* y se corrige. No tocaste el modelo ni el bucle; ajustaste una frase.

> **La calidad de tus trazas determina tu capacidad de optimizar.** Un agente que registra acción, argumentos y observación en cada paso es un agente que puedes mejorar; uno que solo devuelve el resultado final es una caja negra. No consigues un agente mejor esperando un modelo mejor: lo consigues eligiendo la forma adecuada y afinando las tools hasta que las trazas tienen el aspecto que deben tener. Es tunable, es medible, y es tu trabajo.

---

# Parte 6 — Cuánto cuesta un agente

Un agente hace el mismo trabajo que un pipeline y puede costar varias veces más. No es un defecto de implementación: es **el precio estructural de la autonomía**. Pero "el agente es más caro" no es un número con el que puedas presupuestar. El objetivo: convertir esa frase vaga en algo medible.

## De dónde sale el sobrecoste: cuatro fuentes que se suman

1. **Más llamadas al modelo.** Un pipeline hace una o dos por estimación; un agente, una por cada vuelta. Ocho vueltas = ocho llamadas → factor de cuatro solo en número.
2. **El contexto crece en cada vuelta — el factor dominante.** En cada iteración el agente reenvía todo lo acumulado: transcripción, decisiones previas, cada observación de cada tool. La octava llamada cuesta como la primera **más siete rondas de observaciones arrastradas**. Los tokens de entrada (los que más se facturan en volumen) engordan vuelta a vuelta. El coste no es lineal en el número de pasos.
3. **Tokens de razonamiento.** Los modelos de razonamiento deliberan antes de responder, y esos tokens se facturan; en un agente el modelo razona en cada vuelta, así que se paga repetidamente.
4. **Exploración y reintentos.** Reformular una búsqueda pobre, deshacer una línea muerta — cada paso es correcto (el agente adaptándose) pero cuesta tokens que un pipeline no gasta.

Ninguno es evitable del todo; son la contrapartida de la flexibilidad. El segundo es donde está la mayor parte del dinero y, por tanto, la mayor palanca.

## La cuenta del 5×

Números ilustrativos sobre una transcripción compleja. El **pipeline** hace dos llamadas con contexto acotado: pongamos ~8.000 tokens en total. El **agente** da ocho vueltas, y sus tokens de entrada no son constantes: la primera envía ~2.000 (solo la transcripción), pero cada vuelta añade la observación anterior → sube a 4.000, 6.000, y para la octava ronda ~9.000, porque arrastra todo lo visto. Promediando: ~40.000 tokens de entrada + ~8.000 de salida y razonamiento ≈ **48.000 tokens frente a los 8.000 del pipeline. Ahí tienes tu factor de seis** — y casi todo el sobrecoste está en esos tokens de entrada que crecen, no en las respuestas. Traducido a dinero (regla mental: ~10 céntimos ≈ 30–50 mil tokens) y multiplicado por volumen —un millón de tareas al mes a 5× de más— son ~millón y medio de dólares al año de más. **El multiplicador depende por completo del caso, y sin medirlo estás presupuestando a ciegas.**

## Cómo medirlo

La buena noticia: el coste de un agente es de los problemas más medibles que tiene — cada respuesta trae un campo `usage` con tokens de entrada, de salida, y (en modelos de razonamiento) cuántos de salida fueron razonamiento. Un **ledger** que acumule `usage` a lo largo del bucle (`ledger.add(response.usage)` tras cada llamada) da visibilidad total. Un detalle que no equivocar: **los tokens de razonamiento se facturan como salida y ya están contados dentro de `output_tokens` — no los sumes aparte o duplicas el coste.** Los llevas por separado solo para ver qué fracción del gasto es deliberación (a veces la mitad de la factura es el modelo pensando — señal accionable).

Tres cosas que medir más allá del total por ejecución:

- **Coste por paso** — revela el crecimiento del contexto; si la última llamada cuesta 5× la primera, ya sabes dónde está tu dinero.
- **La distribución, no la media** — los agentes tienen cola larga: un agente confundido que itera hasta el límite es tu peor caso y te arruina el promedio. Mide el **percentil 95**.
- **La comparación con el pipeline sobre las mismas entradas** — lo que importa no es el coste absoluto sino el **sobrecoste frente a la alternativa más barata**. Ese ratio justifica o no la autonomía.

Y una atribución que paga con creces: **qué tool infla el contexto.** Si registras el tamaño de la observación de cada tool, descubres si el coste creciente viene de que `search_budgets` devuelve payloads enormes que luego se arrastran. Eso convierte "el agente es caro" en "el 60% del coste es el arrastre de resultados de búsqueda sin adelgazar" — un problema con solución.

## Cómo controlarlo (palancas por impacto)

1. **Enruta.** La palanca más grande no está dentro del agente sino antes: no mandes al agente lo que un pipeline resolvería. La mayoría de tus entradas probablemente no exigen autonomía.
2. **Adelgaza el contexto.** Como su crecimiento domina el coste por ejecución, recortarlo es la mayor palanca dentro del bucle: resume observaciones viejas, descarta irrelevantes, guarda identificadores en vez de payloads. Que `search_budgets` devuelva cinco referencias limpias en vez de doscientas filas mejora las decisiones **y** reduce lo que reenvías cada vuelta.
3. **Acota la cola.** `MAX_STEPS` pone techo al peor caso; complétalo con un **presupuesto por ejecución** — si una estimación supera un umbral de tokens o coste, córtala y trátala como caso para revisión.
4. **Ajusta modelo y razonamiento al trabajo.** No toda decisión necesita el máximo esfuerzo ni el modelo más caro. Reserva la potencia para la orquestación; considera un modelo más barato o menos esfuerzo para sub-tareas acotadas. El nivel de razonamiento es un dial de coste directo.
5. **Cachea lo determinista.** Si el agente repite búsquedas equivalentes entre ejecuciones, una caché evita pagar dos veces. Donde aplica, es dinero gratis.

> Ninguna de estas palancas es exótica — enrutado, gestión de estado, límites, selección de recursos y cacheo: el repertorio de siempre para operar cualquier proceso caro. **El coste de un agente no es un misterio de la IA:** es medible hasta el token, atribuible por paso, controlable con ingeniería corriente. Y de ahí sale el marco correcto: un agente no es "mejor" que un pipeline, es un intercambio distinto entre coste y capacidad. La pregunta no es si el agente funciona —casi siempre funciona—, sino si el valor que aporta en tu caso justifica el multiplicador que acabas de medir.

---

# Chuleta de una página

| Concepto | Qué es / resuelve | Cuándo SÍ | Cuándo NO | Coste / palanca |
|---|---|---|---|---|
| **Pipeline** | Pasos fijos que tú escribes | Forma del problema conocida (la mayoría) | Número/orden de pasos depende de la entrada | 1–2 llamadas, predecible |
| **Workflow** | Varias llamadas encadenadas por ti | RAG bien hecho, ramas enumerables | Árbol de decisión no pre-mapeable | N llamadas fijas |
| **Agente (bucle)** | El modelo elige el siguiente paso | Forma variable + alto valor + error verificable | Puedes pre-mapear las ramas | Multiplicador medible (≈5×) |
| **Function calling** | El modelo pide, tú ejecutas | Siempre que el agente deba actuar | — (es el mecanismo base) | Schema + registro nombre→función |
| **Schema estricto** | Argumentos ceñidos al JSON Schema | Toda tool | — | Garantiza forma, no sentido |
| **Llamadas en paralelo** | Varias `function_call` en una vuelta | Componentes independientes | Pasos dependientes entre sí | `asyncio.gather`, recorta latencia |
| **Descripción de tool** | Dirige qué elige el modelo | Siempre; iterar mirando trazas | — (es la mayor palanca) | Un campo de texto |
| **Observación informativa** | Error como dato recuperable | Toda tool, incluidos fallos | Genérico "error" (deja ciego al agente) | Identificadores estables, lo justo |
| **Handover** | Escalar a humano / delegar | Baja confianza o acción irreversible | Todo verificable y reversible | `status=needs_review` + contrato |
| **Condición de parada** | Guarda del bucle | Siempre (`MAX_STEPS` + presupuesto) | — (nunca omitir) | Amputa la cola larga |
| **Enrutado** | Simple→pipeline, complejo→agente | Distribución mayoritariamente simple | Todo es complejo de verdad | Clasificación barata al principio |
| **Adelgazar contexto** | Frena el coste que engorda por vuelta | Agentes largos / observaciones grandes | Bucles cortos | Resumir/descartar/ids |
| **Ledger de coste** | Mide `usage` por paso | Siempre en producción | — | Coste por paso, p95, ratio vs pipeline |

**La meta-lección, otra vez:** un agente es una decisión de control de flujo con una pieza nueva y acotada en medio —`model.decide`—. Todo lo demás es ingeniería que ya sabes hacer: contratos claros, validación, errores informativos, observabilidad, límites y presupuesto. Empieza siempre por la solución más simple que pase tus pruebas. Sube de tarea a workflow, de workflow a agente, **solo cuando la forma del problema te obligue**. Por defecto, el pipeline. El agente, cuando no te quede otra.

---

## Cómo conecta con nuestro ejercicio

- **Nuestro sistema es hoy un workflow, no un agente.** El pipeline de generación (`app/generation/rag/estimator.py`: reformular → embed → recuperar → truncar a presupuesto → augment → generar → validar) es exactamente el "workflow" de la Parte 1 — pasos que **nosotros** escribimos en orden fijo. No hay `model.decide`: el modelo rellena huecos, no elige el siguiente paso. Eso es lo correcto para la mayoría de transcripciones, y la sesión lo confirma: el pipeline es el estado por defecto.
- **Ya tenemos un bucle iterativo, pero es Actor-Critic-Boss, no function-calling.** `app/generation/agentic/` (`boss.py` + `critic.py`) implementa un bucle de refinamiento iterativo: el Boss es una máquina de estados (`actor_call → critic_review → decide → accept/iterate/fallback`) con traza reproducible en `BossTrace.iterations`. **Es un agente en el sentido de "bucle con estado y condición de parada" (Parte 2) y ya hace handover** (`needs_review` / graceful degradation cuando el Critic falla), pero **el control de flujo lo escribimos nosotros** — el Boss "no hace LLM calls de su propia" y las ramas están codificadas. En la taxonomía de la sesión sigue siendo un workflow sofisticado, no un agente donde el modelo dirige. La brecha real de S12 es esa: no hay `TOOLS`, ni `function_call`/`tool_use`, ni un `model.decide(tools=...)` que deje al modelo secuenciar acciones.
- **La pieza más clara que falta es function calling (Partes 3 y 4).** Un grep confirma cero `function_call`, `tool_use`, `input_schema`, `previous_response_id` o listas de `tools=` en `app/generation/`. Portar el patrón es barato y encaja con lo que dice la Parte 1: **promocionar los pasos del workflow a tools** — `search_budgets` envuelve `retriever.py`/`app/generation/rag/retrieval`, `calculate_estimate` envuelve `task_hours.py`, `validate_estimate` envuelve `validation.py`. No se reimplementa nada; se escribe el schema y se conecta a funciones que ya existen.
- **El caso que justifica un agente ya está en nuestro dominio.** Las transcripciones multi-componente (portal + integración ERP + app móvil + migración legacy) son el ejemplo canónico de "forma variable" de la Parte 1, y nuestro corpus tiene transcripciones de dificultad graduada (`examples/` de S9: `01_clear`, `02_ambiguous`, `03_hard`) que sirven para el **enrutado** (Parte 5) y para leer trazas al optimizar tools.
- **La observabilidad y el coste ya tienen dónde engancharse.** Tenemos `app/generation/rag/observability.py` y telemetría por DB (divergencia nuestra), así que el **ledger de la Parte 6** (coste por paso, p95, ratio vs pipeline, atribución por tool) se cablea sobre infraestructura existente en lugar de crearla de cero. Es la métrica natural a añadir si se porta el agente, para decidir con datos si el multiplicador compensa.
- **Corpus pequeño (15/5/4, 60 tareas):** como en S10/S11, refuerza la recomendación de la sesión de **empezar simple y enrutar** — con la mayoría de transcripciones simples, pagar el bucle iterativo (y su 5×) en todas sería el error de coste que describe la Parte 6. El agente entra como segunda vía para las pocas transcripciones cuya forma no cabe en el pipeline, no como sustituto.
