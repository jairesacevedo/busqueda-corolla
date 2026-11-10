"""Ejecución diaria de las 8:00: búsqueda -> descarga -> consolidación (-> análisis, siguiente fase).

Uso:
    python -m corolla.pipeline --modo prueba
    python -m corolla.pipeline --modo real --esperar-hasta 08:00
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime

from . import config as cfg
from .consolidar import consolidar, exportar_csv
from .logs import etapa
from .recolectar import etapa_busqueda, etapa_descarga


def esperar_hasta(hhmm: str) -> None:
    """GitHub puede arrancar tarde o temprano; si es temprano, esperamos a la hora exacta."""
    h, m = map(int, hhmm.split(":"))
    objetivo = cfg.ahora().replace(hour=h, minute=m, second=0, microsecond=0)
    faltan = (objetivo - cfg.ahora()).total_seconds()
    if 0 < faltan <= 3600:
        print(f"Esperando {faltan:.0f} s hasta las {hhmm} (America/Bogota)...", flush=True)
        time.sleep(faltan)


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--modo", choices=["real", "prueba"], default=os.getenv("COROLLA_MODO", "prueba"))
    p.add_argument("--fecha", help="AAAA-MM-DD (por defecto hoy en Bogotá)")
    p.add_argument("--esperar-hasta", help="HH:MM en hora Colombia")
    a = p.parse_args(argv)
    os.environ["COROLLA_MODO"] = a.modo
    if a.esperar_hasta:
        esperar_hasta(a.esperar_hasta)

    inicio = cfg.ahora()
    fecha = a.fecha or inicio.date().isoformat()
    run = ("PRUEBA-" if a.modo == "prueba" else "") + inicio.strftime("%Y%m%d-%H%M%S")
    rt = cfg.rutas(fecha, a.modo)
    print(f"Ejecución {run} · modo {a.modo} · fecha {fecha}", flush=True)
    codigo = 0

    try:
        with etapa(rt["log"], run, a.modo, "busqueda") as reg:
            est = etapa_busqueda(fecha, run, a.modo)
            m = est["meta"]
            reg.update(enlaces_encontrados=m["enlaces_encontrados"], busqueda_completa=m["busqueda_completa"],
                       descargas_pendientes=m["enlaces_encontrados"], errores="; ".join(m["errores"]))
            if not m["busqueda_completa"]:
                reg["estado"] = "parcial"
            print(f"  búsqueda: {m['enlaces_encontrados']} enlaces · completa={m['busqueda_completa']}", flush=True)

        with etapa(rt["log"], run, a.modo, "descarga") as reg:
            r = etapa_descarga(est)
            reg.update(enlaces_encontrados=m["enlaces_encontrados"], **r)
            if r["descargas_fallidas"]:
                reg["estado"] = "parcial"
            print(f"  descarga: {r['descargas_ok']} ok · {r['descargas_fallidas']} fallidas", flush=True)

        with etapa(rt["log"], run, a.modo, "consolidacion") as reg:
            c = consolidar(rt["enlaces"], rt["datos"], rt["db"], rt["meta"])
            exportar_csv(rt["db"], rt["export"])
            reg.update({k: v for k, v in c.items() if k in
                        {"anuncios_nuevos", "registros_agregados", "registros_actualizados",
                         "registros_sin_cambio", "anuncios_unicos_total", "busqueda_completa"}})
            reg["enlaces_encontrados"] = m["enlaces_encontrados"]
            reg["tamano_db_kb"] = round(rt["db"].stat().st_size / 1024, 1)
            if c["estado"] == "omitido":
                reg.update(estado="omitido", errores=c["motivo"])
            print(f"  consolidación: {c}", flush=True)
    except Exception as e:  # el error ya quedó en el log de la etapa
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        codigo = 1
    return codigo


if __name__ == "__main__":
    sys.exit(main())
