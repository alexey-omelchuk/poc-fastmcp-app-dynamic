# Exploración · Formulario de OT generado dinámicamente por el LLM (FastMCP Apps)

Continuación de la [POC v1](https://github.com/alexey-omelchuk/poc-fastmcp-app), donde el formulario era fijo
y estaba programado en el servidor. Aquí el formulario **lo diseña el propio LLM** a partir de una
**definición que vive en el MCP** (`formularios/alta_ot.json`). Se guarda igual que antes, en la misma tabla
SQLite, mediante otra herramienta (`guardar_ot`).

![Demo](docs/demo.gif)

> Datos de demo: equipos **ficticios** (P-101, C-201, M-301, V-401). Vídeo completo (2 min): [`docs/demo.mp4`](docs/demo.mp4).
> Es una **exploración**. Conclusiones y riesgos en [docs/EXPLORACION.md](docs/EXPLORACION.md).

## Arranque rápido (Docker, en WSL)

```bash
cd "/mnt/c/Users/Alexey7123/Downloads/Nunsys/fastMCP - dynamic"    # comillas: la carpeta tiene espacios
docker compose up -d                          # chat → http://localhost:8011   (MCP en :8010)
docker compose --profile visor up -d          # + visor de FastMCP
docker compose logs visor | grep "dev UI"     # abre ESA URL (http://127.0.0.1:8090/?token=...)
docker compose exec mcp python scripts/ver_db.py
docker compose --profile visor down           # parar
```

Usa **puertos distintos de la v1** (8010/8011/8090), así que puedes tener los dos proyectos a la vez.
La API key de Groq se lee de `../var_entorno_groq.txt` y el modelo se elige automáticamente.

## Qué tiene que salir (botones de inicio del chat)

| Botón | Qué demuestra | Resultado esperado |
|---|---|---|
| **1 · OT del correo (P-101)** | El LLM lee la definición y diseña el formulario | Activo P-101, «Pérdida de agua por el cierre mecánico», Alta, Observaciones. *Crear orden* → OT-DEMO-0001. Dos veces → la misma |
| **2 · Formulario mínimo** | *«Solo quiero el equipo y la avería»* | Solo **Activo** y **Descripción** |
| **3 · Con datos extra** | El LLM añade opcionales según lo que dice el usuario | + Prioridad, **¿Equipo parado?**, **Turno**, **Contacto**. Se guardan en `datos_extra` |
| **4 · Intentar saltarse un obligatorio** | *«Quita el campo de activo»* | Aviso **«Capa de seguridad: Activo es obligatorio, lo añade el servidor»**. Sin activo no se guarda |
| **5 · Ver órdenes guardadas** | Misma tabla que la v1 | Lista con los `datos_extra` |

En cada mensaje puedes desplegar **«Usado abrir_formulario»** para ver el **diseño exacto** que envió el LLM.

## Cómo funciona

```
Usuario → Chainlit + Groq ─► describir_formulario("alta_ot")   ← lee formularios/alta_ot.json (campos + instrucciones)
                          ─► abrir_formulario(campos=[…])      ← el LLM envía su diseño como DATOS (JSON), no código
                                   │ capa de seguridad: solo campos de la definición, tipos fijos,
                                   │ obligatorios siempre, valores validados
                                   ▼
                     renderizador genérico (Prefab) → formulario en el chat
                                   │ «Crear orden»
                                   ▼
                     guardar_ot(valores) → valida contra la definición ORIGINAL → SQLite (misma tabla)
```

| Archivo | Qué hace |
|---|---|
| `formularios/alta_ot.json` | **La definición del formulario** (campos, tipos, obligatorios, opciones e instrucciones para el LLM). Se edita **sin tocar código** |
| `formularios.py` | Carga las definiciones y la **capa de seguridad**: sanea el diseño del LLM y valida al guardar |
| `server.py` | `describir_formulario` (lo ve el modelo), `abrir_formulario` (`@app.ui`, renderizador genérico) y `guardar_ot` (`@app.tool`, solo la UI) |
| `db.py` | La misma tabla `ordenes` + `datos_extra` (campos sin columna) + `formulario_mostrado` (auditoría) |
| `chat/` | Chainlit + Groq, igual que la v1, pero con flujo de dos pasos (describir → abrir) |
| `tests/test_dinamico.py` | 9 pruebas: diseño, mínimo, obligatorios forzados, campos inventados, validación, extras, idempotencia y campo nuevo sin código |

### Añadir un campo sin escribir código
1. Edita `formularios/alta_ot.json` y añade, por ejemplo:
   `{"nombre": "horas_estimadas", "etiqueta": "Horas estimadas", "tipo": "numero", "obligatorio": false}`
2. `docker compose restart mcp`
3. El agente ya lo conoce y lo puede usar. Se guarda en `datos_extra`.

Tipos disponibles: `texto`, `texto_largo`, `selector`, `si_no`, `numero` y `fecha`.

### Experimento opcional: el LLM escribe el **código** del formulario
FastMCP trae `GenerativeUI`: el LLM escribe código Python de Prefab que se ejecuta en un sandbox (Pyodide).
Para probarlo, crea `.env` con `GENERATIVE_UI=1` y ejecuta `docker compose up -d`. Después, en el chat, pide
*«usa el modo código para crear el formulario de la orden»*. **No se ha podido probar** en el entorno de
desarrollo (necesita descargar Deno y Pyodide de internet). Ver [docs/EXPLORACION.md](docs/EXPLORACION.md).

## Sin Docker
Igual que la v1: servidor y chat en entornos separados.
```bash
python -m venv .venv && source .venv/bin/activate && pip install -r requirements-dev.txt
pytest -q && python server.py                       # MCP en :8000   (o: fastmcp dev apps server.py:mcp)
cd chat && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
MCP_URL=http://localhost:8000/mcp chainlit run app.py --port 8011
```
