"""Paso 1: buscar anuncios en Carroya, descargar cada uno y guardar los dos archivos diarios.

Estados (iguales en ambos archivos):
    sin intentar  -> todavía no se ha iniciado la descarga
    descargado    -> la información se extrajo y quedó guardada
    fallido       -> se intentó, pero ocurrió un error (ver motivo_error)
"""
from __future__ import annotations

import csv
import json
import re
import time
import unicodedata
from pathlib import Path

import requests

from . import config as cfg

LISTAS = ("superHighlights", "megaHighlights", "latestReleases")
SUNROOF = re.compile(r"techo\s+corredizo|techo\s+panor[aá]mico|sun\s?roof|quemacocos", re.I)

COLS_ENLACES = [
    "id_anuncio", "url", "pagina_busqueda", "fecha_hora_descubrimiento",
    "estado_descarga", "fecha_hora_ultimo_intento", "motivo_error", "id_ejecucion",
]
COLS_DATOS = [
    "id_anuncio", "url", "estado_descarga", "fecha_hora_descarga", "motivo_error",
    "marca", "linea", "anio", "version", "precio", "moneda", "kilometraje",
    "transmision", "combustible", "ciudad", "sunroof", "color",
    "fecha_publicacion_carroya", "fecha_actualizacion_carroya", "vendido", "id_ejecucion",
]


# ---------------------------------------------------------------- utilidades
def _slug(texto: str) -> str:
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-") or "colombia"


def url_anuncio(uid: str, anio, ciudad) -> str:
    """La API trae un campo 'detail' mal formado; construimos la URL pública nosotros."""
    return f"https://www.carroya.com/detalle/usado/toyota/corolla/{anio or 'na'}/{_slug(ciudad or '')}/{uid}"


def _vacio(v):
    """Convierte vacíos de la API en None (faltante). No convierte nada en 0."""
    if v is None:
        return None
    if isinstance(v, str) and v.strip() in {"", "null", "None", "N/A", "Nd"}:
        return None
    return v


def _num(v):
    v = _vacio(v)
    if v is None:
        return None
    try:
        n = float(str(v).replace(".", "").replace(",", "")) if isinstance(v, str) else float(v)
    except ValueError:
        return None
    return int(n) if n == int(n) else n


def _texto(v) -> str | None:
    """Pasa listas/diccionarios de la API a texto plano; vacío -> None."""
    if isinstance(v, list):
        v = ", ".join(str(next(iter(a.values()), "")) if isinstance(a, dict) else str(a) for a in v)
    elif isinstance(v, dict):
        v = ", ".join(str(x) for x in v.values())
    return _vacio(v)


def _unir(*valores) -> str | None:
    partes = [t for t in (_texto(v) for v in valores) if t]
    return ", ".join(partes) or None


def detectar_sunroof(accesorios, comentarios) -> str | None:
    """'si' si se menciona; 'no' si hay lista de accesorios sin mención; None si no hay información."""
    acc = _texto(accesorios)
    if SUNROOF.search(f"{acc or ''} {comentarios or ''}"):
        return "si"
    return "no" if acc else None


def _peticion(metodo: str, url: str, **kw) -> requests.Response:
    """Petición con reintentos y espera creciente (1 s, 2 s, 4 s)."""
    ultimo = None
    for intento in range(cfg.REINTENTOS):
        try:
            r = requests.request(metodo, url, headers=cfg.HEADERS, timeout=30, **kw)
            if r.status_code == 200:
                return r
            ultimo = RuntimeError(f"HTTP {r.status_code}")
        except requests.RequestException as e:
            ultimo = e
        time.sleep(2 ** intento)
    raise ultimo


# ---------------------------------------------------------------- búsqueda
def buscar() -> dict:
    """Recorre todas las páginas. Devuelve anuncios únicos y metadatos de completitud."""
    vistos: dict[str, dict] = {}
    count = pages = None
    errores, descartados, paginas_ok = [], 0, 0
    for pagina in range(1, cfg.MAX_PAGINAS + 1):
        cuerpo = {"isReqForRedirect": False, "seoArray": [],
                  "params": {**cfg.PARAMS_BUSQUEDA, "page": str(pagina)}}
        try:
            j = _peticion("POST", f"{cfg.API}/find-filters", json=cuerpo).json()
        except Exception as e:
            errores.append(f"página {pagina}: {type(e).__name__}: {e}")
            break
        paginas_ok += 1
        count, pages = j.get("count", count), j.get("pages", pages)
        lote = [a for k in LISTAS for a in (j.get("results", {}).get(k) or []) if a.get("id")]
        if not lote:
            break
        for a in lote:
            ok = (a.get("brand") == cfg.CRITERIOS["marca"] and a.get("model") == cfg.CRITERIOS["linea"]
                  and cfg.CRITERIOS["anio_min"] <= (a.get("year") or 0) <= cfg.CRITERIOS["anio_max"])
            if not ok:
                descartados += 1
            elif a["id"] not in vistos:
                vistos[a["id"]] = {**a, "_pagina": pagina}
        time.sleep(cfg.PAUSA_S)
    completa = (not errores) and count is not None and (len(vistos) + descartados) >= count
    return {"anuncios": list(vistos.values()), "count_declarado": count, "paginas_declaradas": pages,
            "paginas_consultadas": paginas_ok, "descartados_por_criterio": descartados,
            "busqueda_completa": completa, "errores": errores}


# ---------------------------------------------------------------- descarga
def extraer(d: dict, tarjeta: dict) -> dict:
    """Campos mínimos desde el detalle (lista blanca: nada del vendedor).
    Si un campo falta en el detalle se usa el de la tarjeta de búsqueda; si falta en ambos, queda vacío."""
    def de(clave_det, clave_tar=None):
        v = _vacio(d.get(clave_det))
        return v if v is not None else _vacio(tarjeta.get(clave_tar or clave_det))
    return {
        "marca": de("brand"), "linea": de("model"), "anio": _num(de("year")),
        "version": de("version", "clinea2"), "precio": _num(de("price")),
        "moneda": _vacio(tarjeta.get("ctipomoneda")) or ("PESO" if _num(de("price")) else None),
        "kilometraje": _num(de("kilometers")),
        "transmision": next((t for t in (_vacio(d.get("box")), _vacio(tarjeta.get("ctipocaja")))
                             if t not in (None, "0", 0)), None),  # la API usa "0" como vacío
        "combustible": de("fuel", "ccombustible"), "ciudad": de("city"),
        # se combinan accesorios y comentarios del detalle y de la tarjeta de búsqueda
        "sunroof": detectar_sunroof(_unir(d.get("accessories"), tarjeta.get("caccesorios")),
                                    _unir(d.get("comments"), tarjeta.get("ccomentarios"))),
        "color": de("color"), "fecha_publicacion_carroya": de("fechapublicacion", "cfechapublicacion"),
        "fecha_actualizacion_carroya": de("fechaactualizacion", "cfechaactualizacion"),
        "vendido": de("sold"),
    }


def descargar(uid: str) -> dict:
    r = _peticion("GET", f"{cfg.API}/find-vehicle-detail/{uid}")
    d = r.json().get("data")
    if not isinstance(d, dict) or not d.get("id"):
        raise ValueError("respuesta sin datos del anuncio")
    return d


# ---------------------------------------------------------------- escritura
def _escribir_csv(ruta: Path, columnas: list[str], filas: list[dict]) -> None:
    tmp = ruta.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columnas, extrasaction="ignore")
        w.writeheader()
        for fila in filas:
            w.writerow({c: ("" if fila.get(c) is None else fila.get(c)) for c in columnas})
    tmp.replace(ruta)  # escritura atómica


def etapa_busqueda(fecha: str, id_ejecucion: str, m: str) -> dict:
    """Busca, y guarda ambos archivos con todos los anuncios en estado 'sin intentar'."""
    rt = cfg.rutas(fecha, m)
    rt["dia"].mkdir(parents=True, exist_ok=True)
    t_busqueda = cfg.ahora()
    b = buscar()

    enlaces, datos = [], []
    for a in b["anuncios"]:
        url = url_anuncio(a["id"], a.get("year"), a.get("city"))
        enlaces.append({"id_anuncio": a["id"], "url": url, "pagina_busqueda": a["_pagina"],
                        "fecha_hora_descubrimiento": cfg.iso(t_busqueda), "estado_descarga": "sin intentar",
                        "fecha_hora_ultimo_intento": None, "motivo_error": None, "id_ejecucion": id_ejecucion})
        datos.append({"id_anuncio": a["id"], "url": url, "estado_descarga": "sin intentar",
                      "id_ejecucion": id_ejecucion})
    # Primero se guardan como "sin intentar": si el proceso muere a mitad, queda evidencia.
    _escribir_csv(rt["enlaces"], COLS_ENLACES, enlaces)
    _escribir_csv(rt["datos"], COLS_DATOS, datos)
    meta = {k: v for k, v in b.items() if k != "anuncios"}
    meta.update({"fecha": fecha, "id_ejecucion": id_ejecucion, "fecha_hora_busqueda": cfg.iso(t_busqueda),
                 "enlaces_encontrados": len(enlaces)})
    rt["meta"].write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"rutas": rt, "meta": meta, "enlaces": enlaces, "datos": datos,
            "tarjetas": {a["id"]: a for a in b["anuncios"]}}


def etapa_descarga(est: dict) -> dict:
    """Descarga el detalle de cada anuncio y reescribe ambos archivos con el estado final."""
    rt, enlaces, datos, tarjetas = est["rutas"], est["enlaces"], est["datos"], est["tarjetas"]
    for e, dt in zip(enlaces, datos):
        t = cfg.ahora()
        e["fecha_hora_ultimo_intento"] = cfg.iso(t)
        try:
            det = descargar(e["id_anuncio"])
            dt.update(extraer(det, tarjetas[e["id_anuncio"]]))
            e["estado_descarga"] = dt["estado_descarga"] = "descargado"
            dt["fecha_hora_descarga"] = cfg.iso(cfg.ahora())
        except Exception as ex:
            motivo = f"{type(ex).__name__}: {ex}"[:300]
            e["estado_descarga"] = dt["estado_descarga"] = "fallido"
            e["motivo_error"] = dt["motivo_error"] = motivo
            dt["fecha_hora_descarga"] = None
        time.sleep(cfg.PAUSA_S)

    _escribir_csv(rt["enlaces"], COLS_ENLACES, enlaces)
    _escribir_csv(rt["datos"], COLS_DATOS, datos)
    estados = [d["estado_descarga"] for d in datos]
    return {"descargas_ok": estados.count("descargado"),
            "descargas_fallidas": estados.count("fallido"),
            "descargas_pendientes": estados.count("sin intentar"),
            "errores": "; ".join(sorted({d["motivo_error"] for d in datos if d.get("motivo_error")}))[:500]}
