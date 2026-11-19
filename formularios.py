"""Definiciones de formularios (ficheros JSON en ./formularios) y la «capa de seguridad».

La idea de la exploración: el formulario lo DISEÑA el LLM, pero solo con piezas permitidas.
- `cargar(tipo)`             → definición original (la verdad: campos, tipos, obligatorios, opciones).
- `sanear_diseno(tipo, ...)` → aplica reglas a lo que propone el LLM antes de pintarlo.
- `validar_valores(tipo, …)` → valida lo que envía el usuario contra la definición ORIGINAL al guardar.

Para añadir o quitar campos se edita el JSON; no hace falta tocar este código.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from catalogo import ACTIVOS, normalizar_activo

DIR_FORMULARIOS = Path(os.environ.get("FORMULARIOS_DIR", Path(__file__).parent / "formularios"))

# Tipos de campo que sabe pintar el renderizador genérico (lista cerrada).
TIPOS_PERMITIDOS = {"texto", "texto_largo", "selector", "si_no", "numero", "fecha"}
MAX_ETIQUETA = 80
MAX_AYUDA = 160
MAX_TEXTO_POR_DEFECTO = 1000
SI_NO = {"si": "Sí", "no": "No"}

# Orígenes de opciones dinámicas que puede usar una definición ("opciones_desde").
ORIGENES_OPCIONES = {
    "catalogo_activos": lambda: [{"valor": c, "etiqueta": f"{c} · {d}"} for c, d in ACTIVOS.items()],
}


@lru_cache(maxsize=None)
def _leer(tipo: str) -> dict:
    if not tipo.replace("_", "").isalnum():
        raise ValueError("Tipo de formulario no válido")
    ruta = DIR_FORMULARIOS / f"{tipo}.json"
    if not ruta.is_file():
        raise ValueError(f"No existe el formulario «{tipo}». Disponibles: {', '.join(tipos_disponibles())}")
    definicion = json.loads(ruta.read_text(encoding="utf-8"))
    for c in definicion["campos"]:
        if c["tipo"] not in TIPOS_PERMITIDOS:
            raise ValueError(f"Campo {c['nombre']}: tipo «{c['tipo']}» no permitido")
    return definicion


def tipos_disponibles() -> list[str]:
    return sorted(p.stem for p in DIR_FORMULARIOS.glob("*.json"))


def opciones(campo: dict) -> list[dict]:
    """Opciones de un selector como [{valor, etiqueta}]."""
    if campo["tipo"] == "si_no":
        return [{"valor": v, "etiqueta": e} for v, e in SI_NO.items()]
    if "opciones_desde" in campo:
        return ORIGENES_OPCIONES[campo["opciones_desde"]]()
    return [{"valor": o, "etiqueta": o} for o in campo.get("opciones", [])]


def cargar(tipo: str) -> dict:
    """Definición lista para enseñársela al LLM (con las opciones resueltas)."""
    d = _leer(tipo)
    return {
        "tipo_formulario": d["id"],
        "titulo": d["titulo"],
        "descripcion": d.get("descripcion", ""),
        "instrucciones": d.get("instrucciones", []),
        "tipos_de_campo": sorted(TIPOS_PERMITIDOS),
        "campos": [
            {
                "nombre": c["nombre"],
                "etiqueta": c["etiqueta"],
                "tipo": c["tipo"],
                "obligatorio": c.get("obligatorio", False),
                **({"opciones": [o["valor"] for o in opciones(c)]} if c["tipo"] in ("selector", "si_no") else {}),
                **({"por_defecto": c["por_defecto"]} if "por_defecto" in c else {}),
            }
            for c in d["campos"]
        ],
        "como_abrir": "Llama a abrir_formulario con tipo_formulario, titulo y la lista 'campos' que quieras mostrar "
        "(cada uno con nombre y, opcionalmente, etiqueta, ayuda y valor).",
    }


def _campo_original(tipo: str, nombre: str) -> dict | None:
    return next((c for c in _leer(tipo)["campos"] if c["nombre"] == nombre), None)


def _limpiar_valor(campo: dict, valor) -> tuple[str, str | None]:
    """Normaliza un valor precargado. Devuelve (valor, aviso)."""
    if valor is None or valor == "":
        return "", None
    texto = str(valor).strip()
    if campo["nombre"] == "activo" and campo.get("opciones_desde") == "catalogo_activos":
        cod = normalizar_activo(texto)
        return (cod, None) if cod else ("", f"Activo «{texto}» no está en el catálogo: queda pendiente.")
    if campo["tipo"] in ("selector", "si_no"):
        validos = {o["valor"].lower(): o["valor"] for o in opciones(campo)}
        if campo["tipo"] == "si_no":
            validos.update({"sí": "si", "true": "si", "false": "no"})
        if texto.lower() in validos:
            return validos[texto.lower()], None
        return "", f"«{texto}» no es una opción válida de {campo['nombre']}: se deja vacío."
    limite = campo.get("max_longitud", MAX_TEXTO_POR_DEFECTO)
    if len(texto) > limite:
        return texto[:limite], f"{campo['nombre']}: texto recortado a {limite} caracteres."
    return texto, None


def sanear_diseno(tipo: str, titulo: str | None, campos: list[dict]) -> tuple[dict, list[str]]:
    """Capa de seguridad sobre el diseño que propone el LLM.

    Devuelve (diseño_final, avisos). El diseño final solo contiene campos de la definición,
    con su tipo original, y siempre incluye los obligatorios.
    """
    definicion = _leer(tipo)
    avisos: list[str] = []
    finales: list[dict] = []
    vistos: set[str] = set()

    for propuesto in campos or []:
        nombre = str(propuesto.get("nombre", "")).strip()
        original = _campo_original(tipo, nombre)
        if not original:
            avisos.append(f"Campo «{nombre}» no existe en la definición: descartado.")
            continue
        if nombre in vistos:
            continue
        vistos.add(nombre)
        if propuesto.get("tipo") and propuesto["tipo"] != original["tipo"]:
            avisos.append(f"{nombre}: el tipo lo fija la definición ({original['tipo']}), no el LLM.")
        valor, aviso = _limpiar_valor(original, propuesto.get("valor"))
        if aviso:
            avisos.append(aviso)
        finales.append({
            "nombre": nombre,
            "etiqueta": (str(propuesto.get("etiqueta") or original["etiqueta"]).strip())[:MAX_ETIQUETA],
            "ayuda": (str(propuesto.get("ayuda") or "").strip())[:MAX_AYUDA],
            "tipo": original["tipo"],
            "obligatorio": bool(original.get("obligatorio")),
            "valor": valor,
            "opciones": opciones(original) if original["tipo"] in ("selector", "si_no") else [],
        })

    for original in definicion["campos"]:  # los obligatorios no se negocian
        if original.get("obligatorio") and original["nombre"] not in vistos:
            avisos.append(f"«{original['etiqueta']}» es obligatorio: lo añade el servidor.")
            finales.append({
                "nombre": original["nombre"], "etiqueta": original["etiqueta"], "ayuda": "",
                "tipo": original["tipo"], "obligatorio": True, "valor": "",
                "opciones": opciones(original) if original["tipo"] in ("selector", "si_no") else [],
            })

    titulo_final = (str(titulo).strip() if titulo else definicion["titulo"])[:MAX_ETIQUETA]
    return {"tipo_formulario": tipo, "titulo": titulo_final, "campos": finales}, avisos


def validar_valores(tipo: str, valores: dict) -> tuple[dict, list[str]]:
    """Valida lo que envía el usuario contra la definición ORIGINAL. Devuelve (limpios, errores)."""
    definicion = _leer(tipo)
    valores = valores or {}
    errores: list[str] = []
    limpios: dict = {}
    for nombre in valores:
        if not _campo_original(tipo, nombre):
            errores.append(f"«{nombre}» no es un campo de este formulario.")
    for campo in definicion["campos"]:
        bruto = valores.get(campo["nombre"])
        texto = "" if bruto is None else str(bruto).strip()
        if not texto:
            if campo.get("obligatorio"):
                errores.append(f"{campo['etiqueta']}: es obligatorio.")
            elif "por_defecto" in campo:
                limpios[campo["nombre"]] = campo["por_defecto"]
            continue
        if campo["tipo"] in ("selector", "si_no"):
            validos = [o["valor"] for o in opciones(campo)]
            if texto not in validos:
                errores.append(f"{campo['etiqueta']}: «{texto}» no es válido ({', '.join(validos)}).")
                continue
        elif campo["tipo"] == "numero":
            try:
                float(texto.replace(",", "."))
            except ValueError:
                errores.append(f"{campo['etiqueta']}: debe ser un número.")
                continue
        limite = campo.get("max_longitud", MAX_TEXTO_POR_DEFECTO)
        if len(texto) > limite:
            errores.append(f"{campo['etiqueta']}: máximo {limite} caracteres.")
            continue
        limpios[campo["nombre"]] = texto
    return limpios, errores


def columnas(tipo: str) -> dict[str, str]:
    """campo → columna de la tabla `ordenes` (los demás van a datos_extra)."""
    return {c["nombre"]: c["columna"] for c in _leer(tipo)["campos"] if c.get("columna")}


def recargar() -> None:
    _leer.cache_clear()
