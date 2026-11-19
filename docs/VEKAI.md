# Integración con el chat de VEKAI: estado y punto pendiente

El correo pide comprobar si el chat de VEKAI puede (1) **mostrar el formulario** y (2) **ejecutar la
llamada de guardado desde él**.

## Estado

| Parte | Visor FastMCP (`fastmcp dev apps`) | Chat de demo (Chainlit + Groq) | Chat de VEKAI |
|---|---|---|---|
| El agente extrae activo / descripción / prioridad | Manual (argumentos en el visor) | ✅ LLM de Groq | **Pendiente de probar** |
| Mostrar el formulario (MCP Apps) | ✅ | ✅ | **Pendiente de probar** |
| Guardar desde el formulario (`CallTool` → `guardar_ot`) | ✅ | ✅ | **Pendiente de probar** |

Esta POC no tiene acceso al chat de VEKAI. Por eso la demo queda funcionando en el visor de FastMCP
y en un chat de demo en **Chainlit** que hace de "host" igual que lo haría VEKAI.

## Qué necesita VEKAI para que funcione

VEKAI tiene que comportarse como un **host de MCP Apps** (extensión `io.modelcontextprotocol/ui`):

1. **Conectarse al servidor MCP** (`http://<host>:8000/mcp` con `python server.py`, o stdio con `fastmcp run server.py:mcp`).
2. **Mostrar el formulario:** al llamar a `abrir_formulario`, leer `_meta.ui.resourceUri` del tool, pedir ese recurso `ui://…` y pintarlo en un **iframe sandbox**. El renderer de Prefab carga desde `https://cdn.jsdelivr.net`, que está declarado en el CSP del recurso, así que VEKAI tiene que permitir ese dominio.
3. **Guardar desde el formulario:** reenviar al servidor las peticiones `tools/call` que llegan del iframe por `postMessage`. Esa es la llamada a `guardar_ot`, una herramienta con visibilidad `["app"]`: el modelo no la ve, pero la UI sí puede llamarla.

La forma más rápida de implementarlo es el módulo **AppBridge** de `@modelcontextprotocol/ext-apps`.
Si VEKAI está hecho con Chainlit, `chat/public/elements/McpApp.jsx` (≈80 líneas) y la ruta
`/ot/tools/call` de `chat/app.py` son exactamente lo que hace falta y se pueden copiar.

## Cómo comprobarlo en VEKAI (checklist)

- [ ] VEKAI lista `abrir_formulario` y **no** muestra `guardar_ot` al modelo.
- [ ] Al escribir la frase del correo, el agente llama a `describir_formulario` y después a `abrir_formulario` con P-101 / descripción / Alta.
- [ ] El formulario se ve dentro del chat (si sale texto «Formulario de OT abierto…», VEKAI no pinta MCP Apps → **se detiene en el punto 2**).
- [ ] «Crear orden» muestra «Orden OT-DEMO-0001 creada · Estado: Abierta» (si da error o no hace nada, VEKAI no reenvía `tools/call` → **se detiene en el punto 3**).
- [ ] `python scripts/ver_db.py` muestra una sola fila tras dos envíos.
