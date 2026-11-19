# Exploración: ¿quién construye el formulario?

## Las tres opciones

| | v1 – Formulario fijo | A – Diseño declarativo por el LLM (**esta POC**) | B – El LLM escribe código (GenerativeUI) |
|---|---|---|---|
| Quién decide los campos | El programador, en `server.py` | El LLM, a partir de `formularios/alta_ot.json` | El LLM, libremente |
| Qué envía el LLM | Solo valores | **Datos (JSON)**: campos, etiquetas, ayudas y valores | **Código Python** (Prefab) |
| ¿Se ejecuta código generado? | No | **No** | **Sí** (sandbox Pyodide) |
| Cambiar el formulario | Programar y desplegar | **Editar el JSON** y reiniciar | Cambiar el prompt |
| Se adapta al usuario («solo este campo») | No | **Sí, en los opcionales** | Sí, en todo |
| Obligatorios garantizados | Sí | **Sí** (el servidor los fuerza) | Solo si se valida al guardar |
| Formulario siempre «el mismo» | Sí | Misma definición, presentación variable | No |
| Riesgo | Bajo | **Bajo**: lista cerrada de piezas | Alto: depende del sandbox |
| Esfuerzo para un formulario nuevo | Programar | **Un JSON** | Un prompt |

## Respuesta a lo que se discutió en la reunión

- **«El formulario tiene que ser fiable y el mismo, porque se guarda en base de datos»** → lo que se guarda lo
  valida `guardar_ot` contra la **definición original**, no contra lo que dibujó el LLM. Los datos siempre
  tienen la misma forma (misma tabla; los campos nuevos van en `datos_extra`).
- **«Quiero definir formularios sin escribir código»** → `formularios/alta_ot.json`. Añadir un campo es añadir
  un objeto al JSON (hay una prueba automática que lo comprueba).
- **«Si el técnico dice *solo quiero rellenar este campo*…»** → el LLM quita opcionales (botón 2) o los añade según lo que cuenta el usuario (botones 3 y 4), pero no los
  obligatorios.
- **«Pero por prompt se lo puede saltar»** → la seguridad **no depende del prompt**. Si el LLM (o un usuario
  con prompt injection) quita un obligatorio, el servidor lo vuelve a poner y avisa (botón 5). Y si alguien
  llamara directamente a `guardar_ot` sin él, se rechaza.
- **«Si dejas ejecutar código dinámico…»** → en el enfoque A **no se ejecuta código del LLM**: solo se aceptan
  datos de una lista cerrada (6 tipos de campo). El enfoque B sí ejecuta código y queda como experimento.

## Capa de seguridad implementada (enfoque A)

| Riesgo | Protección |
|---|---|
| El LLM inventa campos (`precio`, `hack`…) | Se descartan y se avisa |
| El LLM cambia el tipo de un campo | El tipo lo fija la definición |
| El LLM (o el usuario por prompt) quita un obligatorio | El servidor lo añade y avisa |
| Valores precargados inválidos (opción que no existe, equipo fuera de catálogo) | Se vacían y se avisa |
| Textos enormes o inyección de HTML en etiquetas | Longitudes limitadas; Prefab pinta texto, no HTML; iframe aislado |
| Saltarse el formulario y llamar a guardar | `guardar_ot` solo la puede llamar la UI y valida contra la definición |
| Doble clic o reintentos | Idempotencia por `solicitud_id` |
| Auditoría: ¿qué vio el usuario? | Se guarda `formulario_mostrado` con la orden |

## Limitaciones y lo que queda por ver

- **El LLM no crea campos nuevos sobre la marcha**, por diseño: solo elige entre los de la definición. Ejemplo
  real: «esto ocurrió a las 2 de la mañana» no tenía dónde ir hasta que se añadió `hora_deteccion` al JSON.
  Mientras no exista el campo, la información va a **Observaciones** (está en las instrucciones). Dejar que el
  LLM creara campos libres rompería la fiabilidad de lo que se guarda; sería el enfoque B o un modo
  «campos libres» que acabaría en `datos_extra` sin validación.
- **Mensajes posteriores**: si el usuario añade datos en otro mensaje, el agente vuelve a abrir el formulario con
  todo lo dicho (nueva solicitud). El formulario anterior se queda en el chat sin guardar.

- **Variabilidad**: el mismo mensaje puede producir etiquetas u orden distintos según el LLM. Si se quiere
  presentación idéntica, basta con que la definición marque etiquetas fijas y que el servidor ignore las del LLM.
- **Coste y latencia**: hacen falta dos llamadas al LLM (describir → abrir) en vez de una.
- **Enfoque B (código)**: no se ha podido probar aquí (el entorno bloquea `deno.land` y las CDN). Si se prueba,
  hay que revisar: qué puede hacer el código en el sandbox, tiempo y memoria máximos, que el botón solo pueda
  llamar a `guardar_ot` y, sobre todo, que `guardar_ot` siga validando todo en el servidor.
- **Siguiente paso posible**: un editor sencillo de definiciones (o guardarlas en BD) y varias definiciones
  (`alta_ot`, `cierre_ot`, `inspeccion`…). El código ya admite varios ficheros en `formularios/`.

## Conclusión
El enfoque **A** cumple lo pedido: el formulario se genera dinámicamente desde el MCP, se puede cambiar sin
código y se adapta al usuario, **sin ejecutar código del LLM** y con los datos guardados de forma fiable. Es el
recomendado para seguir. El **B** da más libertad, pero obliga a resolver la seguridad del sandbox antes de
plantearlo en serio.
