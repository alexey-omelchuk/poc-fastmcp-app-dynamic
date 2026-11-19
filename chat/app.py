"""Chat de demo en Chainlit (agente con LLM de Groq) para la exploración «formulario dinámico».

Hace el papel del chat de VEKAI:
  1. El usuario describe la avería.
  2. Groq llama a `describir_formulario` → recibe la definición del formulario (vive en el MCP).
  3. Groq DISEÑA el formulario y llama a `abrir_formulario` con la lista de campos (datos, no código).
  4. Chainlit pinta la interfaz que devuelve el servidor (MCP App) con `public/elements/McpApp.jsx`.
  5. «Crear orden» → el componente pide a este backend que llame a `guardar_ot`.

Chainlit no pinta MCP Apps de serie: `McpApp.jsx` hace de host (iframe + puente postMessage).

Variables de entorno:
  MCP_URL        URL del servidor FastMCP (por defecto http://localhost:8000/mcp)
  GROQ_API_KEY   clave de Groq; si no está, se lee de GROQ_ENV_FILE
  GROQ_ENV_FILE  fichero con GROQ_API_KEY=... (por defecto ../../var_entorno_groq.txt)
  GROQ_MODEL     modelo de Groq (opcional; si no se indica o no existe, se elige uno disponible)

Arranque:  chainlit run app.py --port 8001
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path

import chainlit as cl
from chainlit.server import app as fastapi_app
from fastapi import HTTPException
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

MCP_URL = os.environ.get("MCP_URL", "http://localhost:8000/mcp")
GROQ_BASE_URL = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "").strip()  # vacío = se elige solo uno disponible en tu cuenta
# Preferencia si GROQ_MODEL no está o no existe en la cuenta (modelos con llamada a herramientas)
MODELOS_PREFERIDOS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "llama-3.3-70b-versatile",
    "moonshotai/kimi-k2-instruct",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "qwen/qwen3-32b",
    "llama-3.1-8b-instant",
]
_modelo_elegido: str | None = None
SYSTEM_PROMPT = """Eres el agente de mantenimiento de VEKAI (demo). Hablas en español, de forma breve.
Para crear una orden de trabajo (cuando el usuario describa una avería o lo pida):
1. Llama a describir_formulario con tipo_formulario="alta_ot" para leer la definición y sus instrucciones.
2. Diseña el formulario siguiendo ESAS instrucciones y llama a abrir_formulario con la lista de campos
   (nombre, y si procede etiqueta, ayuda y valor precargado con lo que ha dicho el usuario).
Si el usuario pide un formulario con pocos campos, respeta su petición en los opcionales.
No inventes datos. No digas que la orden está creada: el usuario revisa y pulsa «Crear orden».
Si el servidor devuelve avisos, explícalos en una frase.
Si te preguntan por órdenes ya guardadas, usa listar_ot (el chat mostrará la tabla completa).
Solo si el usuario pide expresamente el «modo código» y existe la herramienta generate_prefab_ui, puedes
escribir tú el código Prefab del formulario con ella; el botón debe usar CallTool("guardar_ot",
arguments={"solicitud_id": "<id único>", "valores": {...}})."""


def _inline_refs(schema: dict) -> dict:
    """Groq/OpenAI se llevan mejor con esquemas sin $ref: se sustituyen por su definición."""
    defs = schema.get("$defs", {})

    def resolver(nodo):
        if isinstance(nodo, dict):
            if "$ref" in nodo and nodo["$ref"].startswith("#/$defs/"):
                return resolver(defs[nodo["$ref"].split("/")[-1]])
            return {k: resolver(v) for k, v in nodo.items() if k != "$defs"}
        if isinstance(nodo, list):
            return [resolver(x) for x in nodo]
        return nodo

    return resolver(schema)


COLUMNAS_OT = ["id", "activo", "prioridad", "estado", "descripcion", "observaciones", "datos_extra", "solicitud_id", "creada_en"]
TITULOS_OT = ["ID", "Activo", "Prioridad", "Estado", "Descripción", "Observaciones", "Datos extra", "Solicitud", "Creada (UTC)"]


def _tabla_ordenes(filas: list[dict]) -> str:
    """Tabla Markdown con TODOS los campos de las órdenes (los mismos que scripts/ver_db.py)."""
    if not filas:
        return "No hay órdenes guardadas."

    def celda(col, v):
        if col == "datos_extra":
            try:
                extra = json.loads(v) if isinstance(v, str) else (v or {})
            except ValueError:
                extra = {}
            v = " · ".join(f"{k}: {x}" for k, x in extra.items()) if extra else "—"
        if col == "creada_en" and isinstance(v, str):
            v = v.replace("T", " ")[:16]  # 2026-11-19 15:20
        texto = str(v if v not in (None, "") else "—")
        return texto.replace("|", "\\|").replace("\n", " ")

    cab = "| " + " | ".join(TITULOS_OT) + " |\n|" + "---|" * len(COLUMNAS_OT) + "\n"
    cuerpo = "\n".join("| " + " | ".join(celda(c, f.get(c)) for c in COLUMNAS_OT) + " |" for f in filas)
    return f"**Órdenes guardadas: {len(filas)}**\n\n{cab}{cuerpo}"


def _tiene_ui(tool) -> bool:
    return bool(((tool.meta or {}).get("ui") or {}).get("resourceUri"))


# ─── MCP ─────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def mcp_session():
    async with streamablehttp_client(MCP_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def _visibilidad(tool) -> list[str]:
    return ((tool.meta or {}).get("ui") or {}).get("visibility", ["model"])


def _dump(result) -> dict:
    return result.model_dump(by_alias=True, exclude_none=True, mode="json")


@fastapi_app.post("/ot/tools/call")
async def llamar_herramienta_desde_la_ui(body: dict):
    """El formulario (iframe) llama aquí para ejecutar herramientas del servidor (p. ej. crear_ot).

    Solo se permiten herramientas marcadas como visibles para la app (visibility incluye "app").
    """
    nombre = body.get("name")
    permitido, resultado = False, None
    async with mcp_session() as s:
        tools = {t.name: t for t in (await s.list_tools()).tools}
        if nombre in tools and "app" in _visibilidad(tools[nombre]):
            permitido = True
            resultado = _dump(await s.call_tool(nombre, body.get("arguments") or {}))
    if not permitido:  # se lanza fuera de la sesión MCP para que llegue como 403 y no como 500
        raise HTTPException(status_code=403, detail=f"La interfaz no puede llamar a «{nombre}».")
    return resultado


# ─── Groq ────────────────────────────────────────────────────────────────────
def _cargar_api_key() -> str | None:
    if os.environ.get("GROQ_API_KEY"):
        return os.environ["GROQ_API_KEY"].strip()
    defecto = Path(__file__).resolve().parents[2] / "var_entorno_groq.txt"
    fichero = Path(os.environ.get("GROQ_ENV_FILE", defecto))
    if fichero.is_file():
        for linea in fichero.read_text(encoding="utf-8").splitlines():
            if linea.strip().startswith("GROQ_API_KEY="):
                return linea.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _elegir_modelo(api_key: str) -> str:
    """Usa GROQ_MODEL si existe en la cuenta; si no, el primero disponible de MODELOS_PREFERIDOS."""
    global _modelo_elegido
    if _modelo_elegido:
        return _modelo_elegido
    req = urllib.request.Request(
        f"{GROQ_BASE_URL}/models", headers={"Authorization": f"Bearer {api_key}", "User-Agent": "vekai-ot-poc/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            disponibles = [m["id"] for m in json.loads(r.read()).get("data", []) if m.get("active", True)]
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Groq respondió {e.code} al listar modelos: {e.read().decode(errors='replace')[:300]}") from e
    candidatos = ([GROQ_MODEL] if GROQ_MODEL else []) + MODELOS_PREFERIDOS
    elegido = next((m for m in candidatos if m in disponibles), None)
    if not elegido:
        raise RuntimeError(f"Ninguno de los modelos preferidos está disponible. Modelos de tu cuenta: {', '.join(sorted(disponibles))[:500]}")
    if GROQ_MODEL and elegido != GROQ_MODEL:
        print(f"[chat] GROQ_MODEL={GROQ_MODEL} no está disponible; uso {elegido}", flush=True)
    print(f"[chat] Modelo de Groq: {elegido}", flush=True)
    _modelo_elegido = elegido
    return elegido


def _llamar_groq(api_key: str, messages: list[dict], tools: list[dict]) -> dict:
    cuerpo = json.dumps(
        {"model": _elegir_modelo(api_key), "messages": messages, "tools": tools, "tool_choice": "auto", "temperature": 0}
    ).encode()
    req = urllib.request.Request(
        f"{GROQ_BASE_URL}/chat/completions",
        data=cuerpo,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "User-Agent": "vekai-ot-poc/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Groq respondió {e.code}: {e.read().decode(errors='replace')[:300]}") from e


def _error_legible(e: BaseException) -> str:
    """Saca el error real de los ExceptionGroup (anyio/MCP los envuelven en «unhandled errors in a TaskGroup»)."""
    while isinstance(e, BaseExceptionGroup) and e.exceptions:
        e = e.exceptions[0]
    texto = f"{type(e).__name__}: {e}"
    if "urlopen error" in texto or "URLError" in texto or "timed out" in texto:
        texto += "\n→ No se puede llegar a la API de Groq (red, proxy o VPN)."
    elif "Groq respondió 401" in texto:
        texto += "\n→ La API key de Groq no es válida (revisa var_entorno_groq.txt)."
    elif "Groq respondió" in texto:
        texto += "\n→ Error de Groq. Si habla del modelo, pon GROQ_MODEL=<modelo> en un .env (o déjalo vacío para que se elija solo)."
    elif "ConnectError" in texto or "Connection refused" in texto or "Name or service not known" in texto:
        texto += f"\n→ No se puede conectar con el servidor MCP en {MCP_URL}. ¿Está arrancado? (`docker compose ps`)"
    return texto


# ─── Chainlit ────────────────────────────────────────────────────────────────
STARTERS_FILE = Path(os.environ.get("STARTERS_FILE", Path(__file__).parent / "starters.json"))


@cl.set_starters
async def starters():
    """Botones de inicio: se leen de starters.json (edítalo y reinicia el chat; no hace falta tocar código)."""
    try:
        datos = json.loads(STARTERS_FILE.read_text(encoding="utf-8"))
        return [cl.Starter(label=d["label"], message=d["message"]) for d in datos]
    except Exception as e:  # fichero mal escrito → seguimos sin botones
        print(f"[chat] No se pudo leer {STARTERS_FILE}: {e}", flush=True)
        return []


@cl.on_chat_start
async def inicio():
    cl.user_session.set("historial", [])


async def _abrir_formulario(session: ClientSession, tool, args: dict) -> tuple[str, bool]:
    """Ejecuta la herramienta con UI y la pinta en el chat con el componente McpApp. Devuelve (resumen, ok)."""
    resultado = await session.call_tool(tool.name, args)
    resumen = next((c.text for c in resultado.content if getattr(c, "type", "") == "text"), "")
    if resultado.isError:
        return f"Error de la herramienta: {resumen}", False
    uri = tool.meta["ui"]["resourceUri"]
    recurso = (await session.read_resource(uri)).contents[0]
    elemento = cl.CustomElement(
        name="McpApp",
        display="inline",
        props={"toolName": tool.name, "toolInput": args, "toolResult": _dump(resultado), "html": recurso.text},
    )
    await cl.Message(content="He diseñado este formulario a partir de la definición del MCP. Revísalo y pulsa **Crear orden**:", elements=[elemento]).send()
    return resumen, True


@cl.on_message
async def mensaje(msg: cl.Message):
    historial: list[dict] = cl.user_session.get("historial") or []
    historial.append({"role": "user", "content": msg.content})

    api_key = _cargar_api_key()
    if not api_key:
        await cl.Message(content="⚠️ Falta la API key de Groq (GROQ_API_KEY o fichero var_entorno_groq.txt).").send()
        return

    try:
        async with mcp_session() as s:
            mcp_tools = [t for t in (await s.list_tools()).tools if "model" in _visibilidad(t)]  # crear_ot queda fuera
            tools = [{"type": "function", "function": {"name": t.name, "description": t.description or "", "parameters": _inline_refs(t.inputSchema)}} for t in mcp_tools]
            por_nombre = {t.name: t for t in mcp_tools}
            messages = [{"role": "system", "content": SYSTEM_PROMPT}, *historial]

            for _ in range(6):  # p. ej. describir_formulario → abrir_formulario
                resp = await asyncio.to_thread(_llamar_groq, api_key, messages, tools)
                m = resp["choices"][0]["message"]
                llamadas = m.get("tool_calls") or []
                if not llamadas:
                    texto = m.get("content") or ""
                    historial.append({"role": "assistant", "content": texto})
                    await cl.Message(content=texto).send()
                    break
                llamada = llamadas[0]
                nombre = llamada["function"]["name"]
                args = {k: v for k, v in json.loads(llamada["function"].get("arguments") or "{}").items() if v not in (None, "")}
                if nombre in por_nombre and _tiene_ui(por_nombre[nombre]):
                    async with cl.Step(name=nombre, type="tool") as paso:
                        paso.input = args  # aquí se ve el formulario que ha diseñado el LLM
                        resumen, ok = await _abrir_formulario(s, por_nombre[nombre], args)
                        paso.output = resumen
                    if ok:
                        historial.append({"role": "assistant", "content": f"[{nombre}] {resumen}"})
                        break
                    messages += [  # error (p. ej. diseño inválido): se lo devolvemos al modelo para que corrija
                        {"role": "assistant", "content": m.get("content") or "", "tool_calls": [llamada]},
                        {"role": "tool", "tool_call_id": llamada["id"], "content": resumen},
                    ]
                    continue
                # Herramienta de datos (listar_ot): se ejecuta y se devuelve el resultado al modelo.
                async with cl.Step(name=nombre, type="tool") as paso:
                    paso.input = args
                    res = await s.call_tool(nombre, args)
                    salida = res.structuredContent if res.structuredContent is not None else [c.text for c in res.content if hasattr(c, "text")]
                    if res.isError:
                        salida = {"error": " ".join(c.text for c in res.content if hasattr(c, "text"))}
                    if isinstance(salida, dict) and list(salida) == ["result"]:
                        salida = salida["result"]  # MCP envuelve las listas en {"result": [...]}
                    paso.output = salida
                if nombre == "listar_ot" and isinstance(salida, list):
                    # La tabla se pinta directamente desde los datos (no la resume el LLM), con todos los campos.
                    tabla = _tabla_ordenes(salida)
                    await cl.Message(content=tabla).send()
                    historial.append({"role": "assistant", "content": f"[listar_ot] Mostradas {len(salida)} órdenes en una tabla."})
                    break
                messages += [
                    {"role": "assistant", "content": m.get("content") or "", "tool_calls": [llamada]},
                    {"role": "tool", "tool_call_id": llamada["id"], "content": json.dumps(salida, ensure_ascii=False, default=str)},
                ]
    except Exception as e:  # red, clave inválida, servidor MCP caído…
        detalle = _error_legible(e)
        print(f"[chat] Error: {detalle}", flush=True)  # también en `docker compose logs chat`
        await cl.Message(content=f"⚠️ Error: {detalle}").send()
    finally:
        cl.user_session.set("historial", historial)
