"""Persistencia SQLite de las órdenes de trabajo (OT) de demo."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.environ.get("OT_DB_PATH", Path(__file__).parent / "data" / "ordenes.db"))

ESQUEMA = """
CREATE TABLE IF NOT EXISTS ordenes (
    id            TEXT PRIMARY KEY,          -- OT-DEMO-0001
    num           INTEGER NOT NULL UNIQUE,   -- 1, 2, 3...
    solicitud_id  TEXT NOT NULL UNIQUE,      -- un id por formulario → idempotencia
    activo        TEXT NOT NULL,
    descripcion   TEXT NOT NULL,
    prioridad     TEXT NOT NULL CHECK (prioridad IN ('Baja','Normal','Alta')),
    observaciones TEXT NOT NULL DEFAULT '',
    estado        TEXT NOT NULL,
    creada_en     TEXT NOT NULL,
    -- Nuevo en la versión dinámica:
    tipo_formulario     TEXT NOT NULL DEFAULT 'alta_ot',
    datos_extra         TEXT NOT NULL DEFAULT '{}',   -- campos que no tienen columna propia (JSON)
    formulario_mostrado TEXT NOT NULL DEFAULT '{}'    -- diseño que generó el LLM, tras la capa de seguridad (auditoría)
);
"""


def _conectar() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)  # autocommit; transacciones explícitas
    con.row_factory = sqlite3.Row
    con.execute(ESQUEMA)
    return con


def crear_orden_idempotente(
    *,
    solicitud_id: str,
    activo: str,
    descripcion: str,
    prioridad: str,
    observaciones: str,
    estado: str,
    tipo_formulario: str = "alta_ot",
    datos_extra: dict | None = None,
    formulario_mostrado: dict | None = None,
) -> tuple[dict, bool]:
    """Inserta la OT si no existe ya una para `solicitud_id`.

    Devuelve (orden, creada_ahora). Un doble clic o reintento con el mismo `solicitud_id`
    devuelve la orden ya guardada y `creada_ahora=False`.
    """
    con = _conectar()
    try:
        con.execute("BEGIN IMMEDIATE")  # bloquea escrituras concurrentes durante la comprobación
        fila = con.execute("SELECT * FROM ordenes WHERE solicitud_id = ?", (solicitud_id,)).fetchone()
        if fila:
            con.execute("COMMIT")
            return dict(fila), False
        num = con.execute("SELECT COALESCE(MAX(num), 0) + 1 FROM ordenes").fetchone()[0]
        orden = {
            "id": f"OT-DEMO-{num:04d}",
            "num": num,
            "solicitud_id": solicitud_id,
            "activo": activo,
            "descripcion": descripcion,
            "prioridad": prioridad,
            "observaciones": observaciones,
            "estado": estado,
            "creada_en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tipo_formulario": tipo_formulario,
            "datos_extra": json.dumps(datos_extra or {}, ensure_ascii=False),
            "formulario_mostrado": json.dumps(formulario_mostrado or {}, ensure_ascii=False),
        }
        con.execute(
            "INSERT INTO ordenes (id, num, solicitud_id, activo, descripcion, prioridad, observaciones, estado, creada_en,"
            " tipo_formulario, datos_extra, formulario_mostrado)"
            " VALUES (:id, :num, :solicitud_id, :activo, :descripcion, :prioridad, :observaciones, :estado, :creada_en,"
            " :tipo_formulario, :datos_extra, :formulario_mostrado)",
            orden,
        )
        con.execute("COMMIT")
        return orden, True
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def contar_altas(solicitud_id: str) -> int:
    con = _conectar()
    try:
        return con.execute("SELECT COUNT(*) FROM ordenes WHERE solicitud_id = ?", (solicitud_id,)).fetchone()[0]
    finally:
        con.close()


def listar_ordenes(limite: int = 20) -> list[dict]:
    con = _conectar()
    try:
        filas = con.execute("SELECT * FROM ordenes ORDER BY num DESC LIMIT ?", (limite,)).fetchall()
        return [dict(f) for f in filas]
    finally:
        con.close()
