"""POC v2 (exploración) – Formulario de OT generado dinámicamente por el LLM.

Diferencia con la v1: el formulario ya no está programado aquí. La v1 tenía un formulario fijo.
  1. `describir_formulario` → el LLM lee la definición (formularios/alta_ot.json) y sus instrucciones.
  2. El LLM DISEÑA el formulario (campos, orden, etiquetas, ayudas, valores) y lo envía como DATOS
     a `abrir_formulario`.
  3. El servidor aplica la capa de seguridad (formularios.sanear_diseno) y lo pinta con un
     renderizador genérico de Prefab.
  4. «Crear orden» → `guardar_ot` valida contra la definición ORIGINAL y guarda en la misma tabla.

Experimento opcional (GENERATIVE_UI=1): el proveedor oficial GenerativeUI, en el que el LLM escribe
código Prefab que se ejecuta en un sandbox Pyodide. Necesita Deno.

Arranque en local:  fastmcp dev apps server.py:mcp
"""

from __future__ import annotations

import os
import uuid
from typing import Annotated

from fastmcp import FastMCP, FastMCPApp
from fastmcp.exceptions import ToolError
from fastmcp.tools import ToolResult
from prefab_ui.actions import SetState, ShowToast
from prefab_ui.actions.mcp import CallTool
from prefab_ui.app import PrefabApp
from prefab_ui.components import (
    Alert,
    AlertDescription,
    AlertTitle,
    Badge,
    Button,
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
    Column,
    Form,
    If,
    Input,
    Label,
    Muted,
    Row,
    Select,
    SelectOption,
    Textarea,
)
from prefab_ui.rx import ERROR, RESULT, Rx
from pydantic import BaseModel, Field

import db
import formularios
from catalogo import ESTADO_INICIAL

app = FastMCPApp("FormulariosDinamicos")


class CampoPropuesto(BaseModel):
    """Un campo del formulario tal y como lo propone el LLM."""

    nombre: str = Field(description="Nombre del campo tal y como aparece en describir_formulario (p. ej. 'activo').")
    etiqueta: str | None = Field(default=None, description="Texto a mostrar. Si se omite, se usa el de la definición.")
    ayuda: str | None = Field(default=None, description="Ayuda corta opcional bajo el campo.")
    valor: str | None = Field(default=None, description="Valor precargado con lo que ha dicho el usuario. No inventar.")


# ─────────────────────────────────────────────────────────────────────────────
# 1. El LLM lee la definición del formulario (vive en formularios/*.json)
# ─────────────────────────────────────────────────────────────────────────────
@app.tool(model=True)
def describir_formulario(
    tipo_formulario: Annotated[str, Field(description="Tipo de formulario. Para dar de alta una orden de trabajo: 'alta_ot'.")] = "alta_ot",
) -> dict:
    """Devuelve la definición de un formulario (campos, obligatorios, opciones) y las instrucciones para construirlo.

    Llama SIEMPRE a esta herramienta antes de abrir_formulario.
    """
    try:
        return formularios.cargar(tipo_formulario)
    except ValueError as e:
        raise ToolError(str(e)) from e


# ─────────────────────────────────────────────────────────────────────────────
# 2. Renderizador genérico: diseño (datos) → componentes Prefab
# ─────────────────────────────────────────────────────────────────────────────
def _pintar_campo(c: dict) -> None:
    with Column(gap=1):
        with Row(gap=2, align="center"):
            Label(c["etiqueta"] + (" *" if c["obligatorio"] else ""))
            if c["obligatorio"]:
                with If(~Rx(c["nombre"])):
                    Badge("Pendiente", variant="destructive")
        if c["ayuda"]:
            Muted(c["ayuda"])
        if c["tipo"] in ("selector", "si_no"):
            with Select(name=c["nombre"], placeholder="Selecciona…"):
                for o in c["opciones"]:
                    SelectOption(value=o["valor"], label=o["etiqueta"])
        elif c["tipo"] == "texto_largo":
            Textarea(name=c["nombre"], rows=3)
        elif c["tipo"] == "numero":
            Input(name=c["nombre"], input_type="number")
        elif c["tipo"] == "fecha":
            Input(name=c["nombre"], input_type="date")
        else:
            Input(name=c["nombre"])


@app.ui(title="Formulario generado por el agente")
def abrir_formulario(
    campos: Annotated[list[CampoPropuesto], Field(description="Campos a mostrar, en orden. Los obligatorios se añaden siempre.")],
    tipo_formulario: Annotated[str, Field(description="Tipo de formulario (p. ej. 'alta_ot').")] = "alta_ot",
    titulo: Annotated[str | None, Field(description="Título del formulario. Si se omite, el de la definición.")] = None,
) -> ToolResult:
    """Abre en el chat el formulario que has diseñado a partir de describir_formulario.

    Envía solo DATOS (lista de campos con nombre, etiqueta, ayuda y valor). El servidor valida el diseño
    (campos existentes, tipos, obligatorios) antes de mostrarlo. No se guarda nada hasta que el usuario pulse
    «Crear orden».
    """
    try:
        diseno, avisos = formularios.sanear_diseno(
            tipo_formulario, titulo, [c.model_dump() if isinstance(c, BaseModel) else dict(c) for c in campos]
        )
    except ValueError as e:
        raise ToolError(str(e)) from e

    solicitud_id = f"SOL-{uuid.uuid4().hex[:12]}"
    nombres = [c["nombre"] for c in diseno["campos"]]
    estado = {c["nombre"]: c["valor"] for c in diseno["campos"]}
    estado.update({"altas": db.contar_altas(solicitud_id), "guardando": False, "resultado": None, "error": None})

    with Card(css_class="max-w-2xl") as view:
        with CardHeader():
            with Row(gap=2, align="center"):
                CardTitle(diseno["titulo"])
                Badge("Generado por el agente", variant="secondary")
            CardDescription("Formulario diseñado por el LLM a partir de la definición del MCP. Revisa y pulsa «Crear orden».")
        with CardContent():
            with Column(gap=4):
                if avisos:
                    with Alert(variant="warning"):
                        AlertTitle("Capa de seguridad del servidor")
                        AlertDescription(" · ".join(avisos))
                with Form(
                    on_submit=[
                        SetState("guardando", True),
                        SetState("error", None),
                        CallTool(
                            guardar_ot,
                            arguments={
                                "tipo_formulario": tipo_formulario,
                                "solicitud_id": solicitud_id,
                                "valores": {n: Rx(n) for n in nombres},
                            },
                            on_success=[
                                SetState("guardando", False),
                                SetState("resultado", RESULT),
                                SetState("altas", RESULT.altas),
                                ShowToast(RESULT.mensaje, variant="success"),
                            ],
                            on_error=[SetState("guardando", False), SetState("error", ERROR)],
                        ),
                    ]
                ):
                    for c in diseno["campos"]:
                        _pintar_campo(c)
                    Button(Rx("guardando").then("Creando…", "Crear orden"), button_type="submit", disabled=Rx("guardando"))

                with If(Rx("error")):
                    with Alert(variant="destructive"):
                        AlertTitle("No se ha podido crear la orden")
                        AlertDescription(Rx("error"))
                with If(Rx("resultado")):
                    with Alert(variant="success"):
                        AlertTitle(Rx("resultado").mensaje)
                        AlertDescription(f"Solicitud {solicitud_id}.")
                Muted(f"Solicitud {solicitud_id} · Altas registradas para esta solicitud: {{{{ altas }}}} · Campos: {', '.join(nombres)}")

    # Para guardarlo junto a la orden (auditoría): qué formulario se mostró, sin la lista de opciones.
    _disenos[solicitud_id] = {**diseno, "avisos": avisos, "campos": [{k: v for k, v in c.items() if k != "opciones"} for c in diseno["campos"]]}
    resumen = (
        f"Formulario '{diseno['titulo']}' abierto (solicitud {solicitud_id}) con los campos: {', '.join(nombres)}. "
        + (f"Avisos del servidor: {' | '.join(a.rstrip('.') for a in avisos)}. " if avisos else "")
        + "Aún no se ha guardado nada: el usuario debe revisar y pulsar «Crear orden»."
    )
    return ToolResult(content=resumen, structured_content=PrefabApp(view=view, state=estado))


_disenos: dict[str, dict] = {}


# ─────────────────────────────────────────────────────────────────────────────
# 3. Guardar: solo lo llama el formulario; valida contra la definición ORIGINAL
# ─────────────────────────────────────────────────────────────────────────────
@app.tool()
def guardar_ot(solicitud_id: str, valores: dict, tipo_formulario: str = "alta_ot") -> dict:
    """Valida los valores contra la definición del formulario y registra la OT (idempotente por solicitud_id)."""
    if not solicitud_id:
        raise ToolError("Falta el identificador de la solicitud.")
    try:
        limpios, errores = formularios.validar_valores(tipo_formulario, valores)
    except ValueError as e:
        raise ToolError(str(e)) from e
    if errores:
        raise ToolError("Revisa estos campos → " + " | ".join(errores))

    mapa = formularios.columnas(tipo_formulario)
    en_columnas = {mapa[k]: v for k, v in limpios.items() if k in mapa}
    extra = {k: v for k, v in limpios.items() if k not in mapa}
    orden, creada_ahora = db.crear_orden_idempotente(
        solicitud_id=solicitud_id,
        activo=en_columnas.get("activo", ""),
        descripcion=en_columnas.get("descripcion", ""),
        prioridad=en_columnas.get("prioridad", "Normal"),
        observaciones=en_columnas.get("observaciones", ""),
        estado=ESTADO_INICIAL,
        tipo_formulario=tipo_formulario,
        datos_extra=extra,
        formulario_mostrado=_disenos.get(solicitud_id, {}),
    )
    mensaje = f"Orden {orden['id']} creada · Estado: {orden['estado']}"
    if not creada_ahora:
        mensaje += " (reenvío detectado: es la misma orden, no se ha duplicado)"
    return {"id": orden["id"], "estado": orden["estado"], "mensaje": mensaje, "creada_ahora": creada_ahora, "altas": db.contar_altas(solicitud_id)}


@app.tool(model=True)
def listar_ot(limite: int = 10) -> list[dict]:
    """Lista las últimas órdenes de trabajo guardadas (incluye datos_extra)."""
    filas = db.listar_ordenes(limite)
    return [{k: v for k, v in f.items() if k != "formulario_mostrado"} for f in filas]


mcp = FastMCP("VEKAI Mantenimiento – POC formularios dinámicos", providers=[app])

# Experimento B: el LLM escribe código Prefab que se ejecuta en un sandbox (requiere Deno).
if os.environ.get("GENERATIVE_UI", "0") == "1":
    from fastmcp.apps.generative import GenerativeUI

    mcp.add_provider(GenerativeUI())

if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
