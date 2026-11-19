# Plan – Exploración: formulario de OT generado dinámicamente por el LLM

## De dónde sale (reunión)
- El formulario de la v1 era **fijo** (programado en `server.py`). Se pide que lo **genere el propio LLM**
  a partir de una **descripción del formulario que vive en el MCP** ("mini prompt que explica cómo se
  construye un formulario de alta de orden").
- Se guarda **igual que ahora** (misma tabla SQLite), con **otra herramienta para guardar**.
- Objetivo: **explorar**. Ver qué se puede hacer, qué riesgos hay ("si dejas ejecutar código dinámico…")
  y cómo protegerlo.
- Debate de la reunión que hay que poder enseñar:
  - "Quiero definir formularios **sin escribir código**: este campo, este, este".
  - "Si el técnico dice *solo quiero rellenar este campo*, el formulario se adapta".
  - "Pero lo obligatorio es obligatorio; por prompt alguien se lo puede saltar" → **la seguridad no puede
    depender del prompt**.

## Enfoque elegido: dos experimentos

### Experimento A (principal) – Formulario declarativo generado por el LLM
1. La **definición del formulario** está en un fichero de datos: `formularios/alta_ot.json` (campos, tipos,
   obligatorios, opciones e **instrucciones** para el LLM). Para añadir o quitar campos se edita el JSON, sin tocar código.
2. Herramienta **`describir_formulario(tipo)`** (la ve el modelo): devuelve esa definición y las instrucciones.
3. El LLM **diseña el formulario**: qué campos mostrar, en qué orden, con qué etiquetas y ayudas, y qué valores
   precargar. Lo envía como **datos (JSON)**, no como código, a **`abrir_formulario`** (`@app.ui()`).
4. El servidor aplica una **capa de seguridad** antes de pintar:
   - solo se aceptan campos que existen en la definición; el resto se descarta con aviso;
   - el tipo de cada campo lo marca la definición, no el LLM;
   - los obligatorios **se añaden siempre**, aunque el LLM los quite (o se lo pidan por prompt);
   - los valores precargados se validan (p. ej. opciones de un selector) y los textos se limitan.
5. Un **renderizador genérico** convierte la definición resultante en componentes Prefab.
6. **`guardar_ot`** (`@app.tool()`, solo la UI) valida **contra la definición original**, no contra lo que
   generó el LLM, y guarda en la **misma tabla** `ordenes`. Los campos nuevos van a `datos_extra` (JSON) y se guarda
   también el formulario que se mostró (auditoría). Es idempotente por `solicitud_id`, como en la v1.

### Experimento B (opcional) – El LLM escribe el código del formulario (FastMCP *Generative UI*)
- Es el proveedor oficial `GenerativeUI`: el LLM escribe **código Python de Prefab**, que se ejecuta en un
  **sandbox Pyodide** (Deno en el servidor y Pyodide en el navegador).
- Se activa con `GENERATIVE_UI=1`. Sirve para comparar: máxima libertad, pero **ejecuta código generado**.
- Esta POC no lo ha podido probar: el entorno de desarrollo bloquea `deno.land` y las CDN. Está documentado.

## Requisitos verificables
| # | Qué | Cómo se comprueba |
|---|---|---|
| 1 | La frase del correo genera un formulario con P-101 / descripción / Alta | e2e chat + test |
| 2 | "Solo quiero indicar el equipo y la avería" → formulario mínimo | e2e chat |
| 3 | Pedir quitar un obligatorio → el servidor lo vuelve a poner y avisa | test + e2e |
| 4 | Campos desconocidos o valores inválidos del LLM → descartados con aviso | test |
| 5 | Añadir un campo nuevo editando el JSON → aparece y se guarda (datos_extra) | test |
| 6 | `guardar_ot` valida contra la definición, misma tabla, idempotente | test |
| 7 | Abrir no guarda (0 altas) | test |

## Fuera de alcance
Autenticación, sistema real, editor visual de formularios, endurecimiento del experimento B.
