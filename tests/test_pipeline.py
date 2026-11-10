"""Pruebas sin internet: simulan la API de Carroya y verifican estados, faltantes,
consolidación, disponibilidad e idempotencia."""
import csv
import json
import sqlite3

import pytest

from corolla import config as cfg
from corolla import recolectar as rec
from corolla.consolidar import consolidar


class Resp:
    def __init__(self, j, status=200):
        self._j, self.status_code = j, status

    def json(self):
        return self._j


def tarjeta(uid, year=2023, price=100_000_000, km=40_000, acc="Air bag, Alarma", brand="Toyota", model="Corolla"):
    return {"id": uid, "brand": brand, "model": model, "year": year, "price": price,
            "kilometers": km, "city": "BOGOTA", "clinea2": "1.8 CVT SEG", "ctipocaja": "Automática",
            "ccombustible": "Híbrido", "ctipomoneda": "PESO", "caccesorios": acc, "ccomentarios": "",
            "cclienteidusuario": "vendedor@correo.com", "csellername": "Fulano"}


class FakeAPI:
    """Estado de 'Carroya' que cada prueba puede modificar entre días."""
    def __init__(self):
        self.anuncios, self.fallan_detalle, self.falla_pagina = [], set(), None

    def __call__(self, metodo, url, json=None, **kw):
        if url.endswith("/find-filters"):
            p = int(json["params"]["page"])
            if p == self.falla_pagina:
                return Resp({}, 503)
            lote = self.anuncios[(p - 1) * 2: p * 2]  # 2 por página para probar la paginación
            return Resp({"count": len(self.anuncios), "pages": -(-len(self.anuncios) // 2),
                         "results": {"superHighlights": lote}})
        uid = url.rsplit("/", 1)[-1]
        if uid in self.fallan_detalle:
            return Resp({}, 500)
        t = next(a for a in self.anuncios if a["id"] == uid)
        return Resp({"data": {"id": uid, "brand": t["brand"], "model": t["model"], "year": t["year"],
                              "price": t["price"], "kilometers": t["kilometers"], "box": "Automática",
                              "fuel": "Híbrido", "city": "BOGOTA", "version": "1.8 CVT SEG",
                              "accessories": t["caccesorios"], "comments": "", "sold": "N",
                              "plate": "ABC123", "color": "Gris"}})


@pytest.fixture
def api(monkeypatch, tmp_path):
    fake = FakeAPI()
    monkeypatch.setattr(rec.requests, "request", fake)
    monkeypatch.setattr(rec.time, "sleep", lambda s: None)
    monkeypatch.setattr(cfg, "RAIZ", tmp_path)
    return fake


def correr(fecha, run="T"):
    est = rec.etapa_busqueda(fecha, run, "prueba")
    rec.etapa_descarga(est)
    rt = cfg.rutas(fecha, "prueba")
    return rt, consolidar(rt["enlaces"], rt["datos"], rt["db"], rt["meta"])


def leer(ruta):
    with open(ruta, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def q(rt, sql, *p):
    con = sqlite3.connect(rt["db"])
    try:
        return con.execute(sql, p).fetchall()
    finally:
        con.close()


def test_archivos_diarios_estados_y_faltantes(api):
    api.anuncios = [tarjeta("a"), tarjeta("b", km=None, acc=""), tarjeta("c", acc="Techo corredizo"),
                    tarjeta("x", year=2019), tarjeta("y", model="Yaris")]
    api.fallan_detalle = {"b"}
    rt, _ = correr("2026-11-14")
    enl, dat = leer(rt["enlaces"]), leer(rt["datos"])
    # verifica criterios: x (2019) e y (Yaris) se descartan
    assert sorted(e["id_anuncio"] for e in enl) == ["a", "b", "c"]
    assert [e["id_anuncio"] for e in enl] == [d["id_anuncio"] for d in dat]  # consistencia
    est = {d["id_anuncio"]: d for d in dat}
    assert est["a"]["estado_descarga"] == "descargado" and est["a"]["sunroof"] == "no"
    assert est["c"]["sunroof"] == "si"
    # fallido: motivo guardado, campos del vehículo vacíos (no inventados ni en cero)
    assert est["b"]["estado_descarga"] == "fallido" and "HTTP 500" in est["b"]["motivo_error"]
    assert est["b"]["kilometraje"] == "" and est["b"]["precio"] == "" and est["b"]["sunroof"] == ""
    # no se guardan datos personales
    texto = rt["datos"].read_text(encoding="utf-8") + rt["enlaces"].read_text(encoding="utf-8")
    assert "vendedor@correo.com" not in texto and "ABC123" not in texto and "Fulano" not in texto
    meta = json.loads(rt["meta"].read_text(encoding="utf-8"))
    assert meta["busqueda_completa"] is True and meta["descartados_por_criterio"] == 2


def test_sin_intentar_tiene_hora_vacia(api):
    api.anuncios = [tarjeta("a")]
    est = rec.etapa_busqueda("2026-11-14", "T", "prueba")  # sin descargar todavía
    e = leer(est["rutas"]["enlaces"])[0]
    assert e["estado_descarga"] == "sin intentar" and e["fecha_hora_ultimo_intento"] == ""


def test_idempotencia_y_historial(api):
    api.anuncios = [tarjeta("a"), tarjeta("b"), tarjeta("c")]
    rt, r1 = correr("2026-11-14")
    assert r1["registros_agregados"] == 3 and r1["anuncios_unicos_total"] == 3

    # procesar el MISMO archivo otra vez: no cambia nada
    antes = q(rt, "SELECT COUNT(*) FROM observaciones")[0][0]
    r_rep = consolidar(rt["enlaces"], rt["datos"], rt["db"], rt["meta"])
    assert r_rep["estado"] == "omitido"
    assert q(rt, "SELECT COUNT(*) FROM observaciones")[0][0] == antes

    # día 2: 'a' baja de precio, 'c' desaparece (búsqueda completa), 'd' es nuevo
    api.anuncios = [tarjeta("a", price=95_000_000), tarjeta("b"), tarjeta("d")]
    rt, r2 = correr("2026-11-15")
    assert r2["anuncios_nuevos"] == 1 and r2["registros_actualizados"] == 1 and r2["registros_sin_cambio"] == 1
    assert q(rt, "SELECT campo, valor_anterior, valor_nuevo FROM cambios WHERE id_anuncio='a'") == \
        [("precio", "100000000", "95000000")]
    disp = dict(q(rt, "SELECT id_anuncio, disponibilidad_actual FROM anuncios"))
    assert disp == {"a": "encontrado", "b": "encontrado", "c": "no_encontrado", "d": "encontrado"}
    assert q(rt, "SELECT precio, primera_vez_visto, ultima_vez_visto FROM anuncios WHERE id_anuncio='a'") == \
        [(95_000_000, "2026-11-14", "2026-11-15")]
    assert q(rt, "SELECT primera_vez_visto, ultima_vez_visto FROM anuncios WHERE id_anuncio='c'") == \
        [("2026-11-14", "2026-11-14")]

    # reprocesar el día 1 después del día 2 no rompe el estado más reciente
    consolidar(cfg.rutas("2026-11-14", "prueba")["enlaces"], cfg.rutas("2026-11-14", "prueba")["datos"],
               rt["db"], cfg.rutas("2026-11-14", "prueba")["meta"])
    assert q(rt, "SELECT precio FROM anuncios WHERE id_anuncio='a'") == [(95_000_000,)]
    assert q(rt, "SELECT COUNT(*) FROM anuncios")[0][0] == 4


def test_busqueda_incompleta_da_desconocido(api):
    api.anuncios = [tarjeta("a"), tarjeta("b"), tarjeta("c"), tarjeta("d")]
    rt, _ = correr("2026-11-14")
    api.falla_pagina = 2  # se pierde la página 2 (c, d)
    rt, r = correr("2026-11-15")
    assert r["busqueda_completa"] is False
    disp = dict(q(rt, "SELECT id_anuncio, disponibilidad_actual FROM anuncios"))
    assert disp["c"] == "desconocido" and disp["d"] == "desconocido" and disp["a"] == "encontrado"


def test_fallo_de_descarga_sigue_encontrado(api):
    api.anuncios = [tarjeta("a")]
    rt, _ = correr("2026-11-14")
    api.fallan_detalle = {"a"}
    rt, _ = correr("2026-11-15")
    fila = q(rt, "SELECT disponibilidad, estado_descarga FROM observaciones WHERE fecha='2026-11-15'")
    assert fila == [("encontrado", "fallido")]
    # la ficha conserva el último dato válido
    assert q(rt, "SELECT precio FROM anuncios")[0][0] == 100_000_000
