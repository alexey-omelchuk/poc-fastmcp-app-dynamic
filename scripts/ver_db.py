"""Muestra las órdenes guardadas en SQLite.

Uso:
  python scripts/ver_db.py                 # últimas órdenes
  python scripts/ver_db.py SOL-xxxxxxxxxxxx  # altas para una solicitud concreta (0 al abrir, 1 tras crear)
  python scripts/ver_db.py --formulario OT-DEMO-0001  # formulario que diseñó el LLM para esa orden
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db  # noqa: E402

if len(sys.argv) > 2 and sys.argv[1] == "--formulario":
    import json
    fila = next((f for f in db.listar_ordenes(1000) if f["id"] == sys.argv[2]), None)
    print(json.dumps(json.loads(fila["formulario_mostrado"]), ensure_ascii=False, indent=2) if fila else "No existe esa orden")
    sys.exit(0)

if len(sys.argv) > 1:
    sol = sys.argv[1]
    print(f"Altas para {sol}: {db.contar_altas(sol)}")
    sys.exit(0)

filas = db.listar_ordenes(50)
print(f"Base de datos: {db.DB_PATH}")
print(f"Órdenes guardadas: {len(filas)}\n")
cols = ["id", "activo", "prioridad", "estado", "descripcion", "observaciones", "datos_extra", "solicitud_id"]
anchos = {c: max(len(c), *(len(str(f[c])) for f in filas)) if filas else len(c) for c in cols}
print("  ".join(c.ljust(anchos[c]) for c in cols))
print("  ".join("-" * anchos[c] for c in cols))
for f in sorted(filas, key=lambda x: x["num"]):
    print("  ".join(str(f[c]).ljust(anchos[c]) for c in cols))
