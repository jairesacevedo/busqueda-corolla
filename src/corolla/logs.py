"""Log de ejecuciones: una fila por etapa de cada ejecución, en CSV (America/Bogota)."""
from __future__ import annotations

import csv
import time
from contextlib import contextmanager
from pathlib import Path

from .config import ahora, iso

COLUMNAS = [
    "id_ejecucion", "modo", "etapa", "inicio", "fin", "duracion_s", "estado",
    "enlaces_encontrados", "anuncios_nuevos", "descargas_ok", "descargas_fallidas",
    "descargas_pendientes", "registros_agregados", "registros_actualizados",
    "registros_sin_cambio", "anuncios_unicos_total", "tamano_db_kb",
    "busqueda_completa", "errores", "estado_correo",
]


def escribir(ruta: Path, fila: dict) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    nuevo = not ruta.exists()
    with ruta.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, extrasaction="ignore")
        if nuevo:
            w.writeheader()
        w.writerow({c: fila.get(c, "") for c in COLUMNAS})


@contextmanager
def etapa(ruta_log: Path, id_ejecucion: str, modo: str, nombre: str):
    """Mide una etapa y escribe su fila al terminar, incluso si falla.

    Uso:
        with etapa(log, run, modo, "recoleccion") as reg:
            reg["enlaces_encontrados"] = 60
            reg["estado"] = "parcial"   # opcional; por defecto 'ok'
    """
    reg: dict = {"id_ejecucion": id_ejecucion, "modo": modo, "etapa": nombre}
    t0, inicio = time.monotonic(), ahora()
    try:
        yield reg
        reg.setdefault("estado", "ok")
    except Exception as e:
        reg["estado"] = "error"
        reg["errores"] = f"{type(e).__name__}: {e}"[:500]
        raise
    finally:
        reg["inicio"], reg["fin"] = iso(inicio), iso(ahora())
        reg["duracion_s"] = round(time.monotonic() - t0, 1)
        escribir(ruta_log, reg)
