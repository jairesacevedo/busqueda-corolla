"""Pasos 2 y 3: base consolidada en SQLite y función de actualización idempotente.

Tablas
    anuncios             1 fila por anuncio único (UUID de Carroya): ficha más reciente,
                         primera/última vez visto, disponibilidad actual.
    observaciones        1 fila por (anuncio, fecha): disponibilidad del día, estado y hora
                         de la descarga, valores observados ese día.
    cambios              1 fila por (anuncio, fecha, campo) que cambió frente a la observación
                         descargada anterior.
    archivos_procesados  huella sha256 de cada par de archivos diarios ya incorporado.

Disponibilidad
    encontrado      apareció en la búsqueda del día (aunque falle la descarga del detalle)
    no_encontrado   no apareció y la búsqueda fue completa  (NO implica vendido)
    desconocido     no apareció y la búsqueda quedó incompleta por un error
"""
from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from pathlib import Path

from .config import ahora, iso

CAMPOS_VEHICULO = ["marca", "linea", "anio", "version", "precio", "moneda", "kilometraje",
                   "transmision", "combustible", "ciudad", "sunroof", "color",
                   "fecha_publicacion_carroya", "fecha_actualizacion_carroya", "vendido"]
# Campos que se vigilan para detectar cambios (la fecha de actualización de Carroya cambia
# con cualquier edición del vendedor; se guarda pero no se cuenta como cambio del vehículo).
CAMPOS_CAMBIO = [c for c in CAMPOS_VEHICULO if c != "fecha_actualizacion_carroya"]
NUMERICOS = {"anio", "precio", "kilometraje"}

ESQUEMA = f"""
CREATE TABLE IF NOT EXISTS anuncios (
    id_anuncio TEXT PRIMARY KEY,
    url TEXT,
    {", ".join(f"{c} {'INTEGER' if c in NUMERICOS else 'TEXT'}" for c in CAMPOS_VEHICULO)},
    primera_vez_visto TEXT,
    ultima_vez_visto TEXT,
    ultima_descarga_ok TEXT,
    disponibilidad_actual TEXT,
    fecha_ultima_observacion TEXT
);
CREATE TABLE IF NOT EXISTS observaciones (
    id_anuncio TEXT NOT NULL REFERENCES anuncios(id_anuncio),
    fecha TEXT NOT NULL,
    id_ejecucion TEXT,
    disponibilidad TEXT NOT NULL CHECK (disponibilidad IN ('encontrado','no_encontrado','desconocido')),
    estado_descarga TEXT,
    fecha_hora_descarga TEXT,
    motivo_error TEXT,
    {", ".join(f"{c} {'INTEGER' if c in NUMERICOS else 'TEXT'}" for c in CAMPOS_VEHICULO)},
    PRIMARY KEY (id_anuncio, fecha)
);
CREATE TABLE IF NOT EXISTS cambios (
    id_anuncio TEXT NOT NULL,
    fecha TEXT NOT NULL,
    campo TEXT NOT NULL,
    valor_anterior TEXT,
    valor_nuevo TEXT,
    fecha_referencia TEXT,
    PRIMARY KEY (id_anuncio, fecha, campo)
);
CREATE TABLE IF NOT EXISTS archivos_procesados (
    sha256 TEXT PRIMARY KEY,
    fecha TEXT,
    archivo_enlaces TEXT,
    archivo_datos TEXT,
    procesado_en TEXT
);
"""


def conectar(ruta_db: Path) -> sqlite3.Connection:
    ruta_db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ruta_db)
    con.row_factory = sqlite3.Row
    con.executescript(ESQUEMA)
    return con


def _huella(*rutas: Path) -> str:
    h = hashlib.sha256()
    for r in rutas:
        h.update(r.read_bytes())
    return h.hexdigest()


def _leer(ruta: Path) -> list[dict]:
    with ruta.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _norm(campo: str, v):
    """Normaliza un valor leído de CSV: vacío -> None; numéricos -> int."""
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return None
    if campo in NUMERICOS:
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None
    return v


def consolidar(ruta_enlaces: Path, ruta_datos: Path, ruta_db: Path,
               ruta_meta: Path | None = None) -> dict:
    """Incorpora los archivos diarios a la base. Procesar dos veces lo mismo no cambia nada."""
    fecha = ruta_datos.stem.split("_")[-1]
    huella = _huella(ruta_enlaces, ruta_datos)
    con = conectar(ruta_db)
    try:
        if con.execute("SELECT 1 FROM archivos_procesados WHERE sha256=?", (huella,)).fetchone():
            total = con.execute("SELECT COUNT(*) FROM anuncios").fetchone()[0]
            return {"estado": "omitido", "motivo": "archivo ya procesado", "fecha": fecha,
                    "registros_agregados": 0, "registros_actualizados": 0, "registros_sin_cambio": 0,
                    "anuncios_nuevos": 0, "anuncios_unicos_total": total}

        meta = json.loads(ruta_meta.read_text(encoding="utf-8")) if ruta_meta and ruta_meta.exists() else {}
        completa = bool(meta.get("busqueda_completa", False))
        enlaces = {e["id_anuncio"]: e for e in _leer(ruta_enlaces)}
        datos = _leer(ruta_datos)
        ids_hoy = {d["id_anuncio"] for d in datos}
        if set(enlaces) != ids_hoy:
            raise ValueError("enlaces y datos no tienen los mismos anuncios")

        conocidos = {r[0] for r in con.execute("SELECT id_anuncio FROM anuncios")}
        nuevos = agregados = actualizados = sin_cambio = 0
        with con:  # una sola transacción: todo o nada
            for d in datos:
                uid = d["id_anuncio"]
                vals = {c: _norm(c, d.get(c)) for c in CAMPOS_VEHICULO}
                es_nuevo = uid not in conocidos
                if es_nuevo:
                    con.execute("INSERT INTO anuncios (id_anuncio, url) VALUES (?, ?)", (uid, d["url"]))
                    conocidos.add(uid)
                    nuevos += 1
                con.execute(
                    f"""INSERT OR REPLACE INTO observaciones
                        (id_anuncio, fecha, id_ejecucion, disponibilidad, estado_descarga,
                         fecha_hora_descarga, motivo_error, {", ".join(CAMPOS_VEHICULO)})
                        VALUES (?,?,?,?,?,?,?,{", ".join("?" * len(CAMPOS_VEHICULO))})""",
                    (uid, fecha, d.get("id_ejecucion"), "encontrado", d["estado_descarga"],
                     d.get("fecha_hora_descarga") or None, d.get("motivo_error") or None,
                     *vals.values()))

                # Cambios frente a la última observación DESCARGADA anterior a esta fecha
                if d["estado_descarga"] == "descargado":
                    prev = con.execute(
                        """SELECT * FROM observaciones WHERE id_anuncio=? AND fecha<?
                           AND estado_descarga='descargado' ORDER BY fecha DESC LIMIT 1""",
                        (uid, fecha)).fetchone()
                    con.execute("DELETE FROM cambios WHERE id_anuncio=? AND fecha=?", (uid, fecha))
                    difs = []
                    if prev is not None:
                        difs = [(c, prev[c], vals[c]) for c in CAMPOS_CAMBIO
                                if vals[c] is not None and str(prev[c]) != str(vals[c])]
                    for c, antes, despues in difs:
                        con.execute("INSERT INTO cambios VALUES (?,?,?,?,?,?)",
                                    (uid, fecha, c, None if antes is None else str(antes),
                                     str(despues), prev["fecha"]))
                    if es_nuevo:
                        agregados += 1
                    elif difs:
                        actualizados += 1
                    else:
                        sin_cambio += 1
                elif es_nuevo:
                    agregados += 1  # nuevo aunque la descarga falló

            # Anuncios conocidos que HOY no aparecieron
            disp_ausente = "no_encontrado" if completa else "desconocido"
            for uid in conocidos - ids_hoy:
                con.execute(
                    """INSERT OR REPLACE INTO observaciones (id_anuncio, fecha, id_ejecucion, disponibilidad)
                       VALUES (?,?,?,?)""", (uid, fecha, meta.get("id_ejecucion"), disp_ausente))

            _recalcular_anuncios(con)
            con.execute("INSERT INTO archivos_procesados VALUES (?,?,?,?,?)",
                        (huella, fecha, ruta_enlaces.name, ruta_datos.name, iso(ahora())))
        total = con.execute("SELECT COUNT(*) FROM anuncios").fetchone()[0]
        return {"estado": "ok", "fecha": fecha, "busqueda_completa": completa,
                "anuncios_nuevos": nuevos, "registros_agregados": agregados,
                "registros_actualizados": actualizados, "registros_sin_cambio": sin_cambio,
                "no_encontrados_hoy": len(conocidos - ids_hoy) if completa else 0,
                "anuncios_unicos_total": total}
    finally:
        con.close()


def _recalcular_anuncios(con: sqlite3.Connection) -> None:
    """Deriva la ficha de cada anuncio desde observaciones (así no depende del orden de proceso)."""
    con.execute("""
        UPDATE anuncios SET
          primera_vez_visto = (SELECT MIN(fecha) FROM observaciones o
                               WHERE o.id_anuncio=anuncios.id_anuncio AND disponibilidad='encontrado'),
          ultima_vez_visto  = (SELECT MAX(fecha) FROM observaciones o
                               WHERE o.id_anuncio=anuncios.id_anuncio AND disponibilidad='encontrado'),
          ultima_descarga_ok = (SELECT MAX(fecha_hora_descarga) FROM observaciones o
                               WHERE o.id_anuncio=anuncios.id_anuncio AND estado_descarga='descargado'),
          fecha_ultima_observacion = (SELECT MAX(fecha) FROM observaciones o
                               WHERE o.id_anuncio=anuncios.id_anuncio),
          disponibilidad_actual = (SELECT disponibilidad FROM observaciones o
                               WHERE o.id_anuncio=anuncios.id_anuncio ORDER BY fecha DESC LIMIT 1)
    """)
    asignar = ", ".join(f"{c} = (SELECT {c} FROM ult WHERE ult.id_anuncio = anuncios.id_anuncio)"
                        for c in CAMPOS_VEHICULO)
    con.execute(f"""
        WITH ult AS (
          SELECT * FROM observaciones o
          WHERE estado_descarga='descargado' AND fecha = (
              SELECT MAX(fecha) FROM observaciones o2
              WHERE o2.id_anuncio=o.id_anuncio AND o2.estado_descarga='descargado'))
        UPDATE anuncios SET {asignar}
        WHERE id_anuncio IN (SELECT id_anuncio FROM ult)
    """)


def exportar_csv(ruta_db: Path, carpeta: Path) -> None:
    """Copia legible de cada tabla (para revisar sin SQLite y ver diffs en git)."""
    carpeta.mkdir(parents=True, exist_ok=True)
    con = conectar(ruta_db)
    try:
        for t in ("anuncios", "observaciones", "cambios", "archivos_procesados"):
            cur = con.execute(f"SELECT * FROM {t} ORDER BY 1, 2")
            with (carpeta / f"{t}.csv").open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow([c[0] for c in cur.description])
                w.writerows(cur)
    finally:
        con.close()
