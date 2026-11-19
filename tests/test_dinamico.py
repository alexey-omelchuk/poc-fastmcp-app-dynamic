"""Pruebas de la exploración «formulario dinámico» (pytest -q)."""

import importlib
import json
import shutil
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("OT_DB_PATH", str(tmp_path / "ordenes.db"))
    forms = tmp_path / "formularios"
    shutil.copytree(RAIZ / "formularios", forms)
    monkeypatch.setenv("FORMULARIOS_DIR", str(forms))
    import db, formularios
    importlib.reload(db)
    importlib.reload(formularios)
    import server as srv
    importlib.reload(srv)
    srv.forms_dir = forms
    return srv


def _sol(texto: str) -> str:
    return next(w for w in texto.replace(")", " ").split() if w.startswith("SOL-"))


async def _abrir(c, campos, **kw):
    r = await c.call_tool("abrir_formulario", {"campos": campos, **kw})
    return r, r.structured_content["state"], r.content[0].text


async def test_visibilidad(server):
    async with Client(server.mcp) as c:
        t = {x.name: x for x in await c.list_tools()}
    assert "model" in t["describir_formulario"].meta["ui"]["visibility"]
    assert t["abrir_formulario"].meta["ui"]["visibility"] == ["model"]
    assert t["guardar_ot"].meta["ui"]["visibility"] == ["app"]  # el modelo no puede guardar


async def test_describir_devuelve_definicion_e_instrucciones(server):
    async with Client(server.mcp) as c:
        d = (await c.call_tool("describir_formulario", {"tipo_formulario": "alta_ot"})).data
    nombres = {x["nombre"]: x for x in d["campos"]}
    assert nombres["activo"]["obligatorio"] and nombres["descripcion"]["obligatorio"]
    assert nombres["activo"]["opciones"] == ["P-101", "C-201", "M-301", "V-401"]
    assert nombres["prioridad"]["por_defecto"] == "Normal"
    assert d["instrucciones"]


async def test_formulario_precargado_desde_el_chat(server):
    async with Client(server.mcp) as c:
        r, st, txt = await _abrir(c, [
            {"nombre": "activo", "valor": "bomba P-101"},
            {"nombre": "descripcion", "valor": "Pérdida de agua por el cierre mecánico"},
            {"nombre": "prioridad", "valor": "Alta"},
        ])
    assert (st["activo"], st["prioridad"], st["altas"]) == ("P-101", "Alta", 0)
    assert "guardar_ot" in json.dumps(r.structured_content)


async def test_formulario_minimo_solo_lo_pedido(server):
    async with Client(server.mcp) as c:
        _, st, txt = await _abrir(c, [{"nombre": "activo", "valor": "M-301"}, {"nombre": "descripcion", "valor": "Ruido"}])
    assert set(k for k in st if k not in ("altas", "guardando", "resultado", "error")) == {"activo", "descripcion"}
    assert "Avisos" not in txt


async def test_obligatorios_no_se_pueden_quitar(server):
    """Aunque el LLM (o un prompt malicioso) quite el activo, el servidor lo vuelve a poner."""
    async with Client(server.mcp) as c:
        _, st, txt = await _abrir(c, [{"nombre": "descripcion", "valor": "Fuga"}])
    assert "activo" in st and "lo añade el servidor" in txt


async def test_campos_inventados_y_valores_invalidos(server):
    async with Client(server.mcp) as c:
        _, st, txt = await _abrir(c, [
            {"nombre": "activo", "valor": "X-999"},
            {"nombre": "descripcion", "valor": "Fuga"},
            {"nombre": "prioridad", "valor": "Urgentísima"},
            {"nombre": "precio", "valor": "1000"},
            {"nombre": "contacto", "etiqueta": "Contacto " * 30},
        ])
    assert st["activo"] == "" and st["prioridad"] == ""
    assert "precio" not in st and "descartado" in txt and "no está en el catálogo" in txt


async def test_guardar_valida_contra_la_definicion_original(server):
    async with Client(server.mcp) as c:
        with pytest.raises(ToolError) as e:
            await c.call_tool("guardar_ot", {"solicitud_id": "S1", "valores": {"descripcion": " ", "prioridad": "X", "precio": "1"}})
    m = str(e.value)
    assert "Activo" in m and "Descripción" in m and "Prioridad" in m and "precio" in m


async def test_guardar_campos_extra_misma_tabla_e_idempotente(server):
    import db
    async with Client(server.mcp) as c:
        _, st, txt = await _abrir(c, [{"nombre": "activo", "valor": "P-101"}, {"nombre": "descripcion", "valor": "Fuga"}, {"nombre": "turno"}])
        sol = _sol(txt)
        assert db.contar_altas(sol) == 0  # abrir no guarda
        args = {"solicitud_id": sol, "valores": {"activo": "P-101", "descripcion": "Fuga", "turno": "Noche", "equipo_parado": "si"}}
        r1 = (await c.call_tool("guardar_ot", args)).data
        r2 = (await c.call_tool("guardar_ot", args)).data
    assert r1["mensaje"] == "Orden OT-DEMO-0001 creada · Estado: Abierta" and not r2["creada_ahora"]
    fila = db.listar_ordenes()[0]
    assert len(db.listar_ordenes()) == 1 and fila["prioridad"] == "Normal"
    assert json.loads(fila["datos_extra"]) == {"turno": "Noche", "equipo_parado": "si"}
    assert [c["nombre"] for c in json.loads(fila["formulario_mostrado"])["campos"]] == ["activo", "descripcion", "turno"]


async def test_campo_nuevo_sin_tocar_codigo(server, tmp_path):
    """Añadir un campo editando el JSON → el LLM lo ve, se pinta y se guarda en datos_extra."""
    import formularios
    ruta = Path(formularios.DIR_FORMULARIOS) / "alta_ot.json"
    d = json.loads(ruta.read_text(encoding="utf-8"))
    d["campos"].append({"nombre": "horas_estimadas", "etiqueta": "Horas estimadas", "tipo": "numero", "obligatorio": False})
    ruta.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    formularios.recargar()
    async with Client(server.mcp) as c:
        desc = (await c.call_tool("describir_formulario", {})).data
        assert "horas_estimadas" in [x["nombre"] for x in desc["campos"]]
        _, st, txt = await _abrir(c, [{"nombre": "activo", "valor": "C-201"}, {"nombre": "descripcion", "valor": "x"}, {"nombre": "horas_estimadas", "valor": "2"}])
        r = (await c.call_tool("guardar_ot", {"solicitud_id": _sol(txt), "valores": {"activo": "C-201", "descripcion": "x", "horas_estimadas": "2"}})).data
    import db
    assert r["creada_ahora"] and json.loads(db.listar_ordenes()[0]["datos_extra"]) == {"horas_estimadas": "2"}


async def test_campo_hora(server):
    import db
    async with Client(server.mcp) as c:
        desc = (await c.call_tool("describir_formulario", {})).data
        assert "hora_deteccion" in [x["nombre"] for x in desc["campos"]]
        _, st, txt = await _abrir(c, [{"nombre": "activo", "valor": "M-301"}, {"nombre": "descripcion", "valor": "Ruido"},
                                      {"nombre": "hora_deteccion", "valor": "2:00"}])
        assert st["hora_deteccion"] == "02:00"
        _, st2, txt2 = await _abrir(c, [{"nombre": "activo", "valor": "M-301"}, {"nombre": "descripcion", "valor": "x"},
                                        {"nombre": "hora_deteccion", "valor": "las dos"}])
        assert st2["hora_deteccion"] == "" and "no es una hora" in txt2
        with pytest.raises(ToolError):
            await c.call_tool("guardar_ot", {"solicitud_id": "H1", "valores": {"activo": "M-301", "descripcion": "x", "hora_deteccion": "25:99"}})
        r = (await c.call_tool("guardar_ot", {"solicitud_id": _sol(txt), "valores": {"activo": "M-301", "descripcion": "Ruido", "hora_deteccion": "02:00"}})).data
    assert r["creada_ahora"] and json.loads(db.listar_ordenes()[0]["datos_extra"]) == {"hora_deteccion": "02:00"}
