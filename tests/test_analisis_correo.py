"""Pruebas del análisis de gangas y del estado general del correo."""
import pandas as pd

from corolla.analizar import evaluar, posibles_duplicados
from corolla.correo import estado_general


def df(filas):
    base = {"combustible": "Híbrido", "banda_km": "25-50 mil km", "kilometraje": 40000, "transmision": "Automática",
            "version": "1.8", "sunroof": None, "color": "Gris", "ciudad": "Bogota"}
    return pd.DataFrame([{**base, **f} for f in filas])


def test_ganga_detectada_con_explicacion():
    filas = [{"id_anuncio": f"c{i}", "anio": 2023, "precio": p}
             for i, p in enumerate([100e6, 102e6, 104e6, 106e6, 108e6, 110e6])]
    filas.append({"id_anuncio": "barato", "anio": 2023, "precio": 80e6})
    ev = evaluar(df(filas)).set_index("id_anuncio")
    assert ev.loc["barato", "posible_ganga"]
    assert "mediana" in ev.loc["barato", "explicacion"] and ev.loc["barato", "n_comparables"] == 6
    assert not ev.loc["c0", "posible_ganga"]  # el más barato "normal" no es ganga


def test_pocos_comparables_no_se_evalua():
    filas = [{"id_anuncio": "a", "anio": 2022, "precio": 50e6}] + \
            [{"id_anuncio": f"x{i}", "anio": 2026, "precio": 130e6} for i in range(3)]
    ev = evaluar(df(filas)).set_index("id_anuncio")
    assert ev.loc["a", "referencia"] == "datos insuficientes" and not ev.loc["a", "posible_ganga"]


def test_duplicados():
    d = df([{"id_anuncio": "a", "anio": 2025, "precio": 1, "kilometraje": 14000},
            {"id_anuncio": "b", "anio": 2025, "precio": 1, "kilometraje": 14100},
            {"id_anuncio": "c", "anio": 2025, "precio": 1, "kilometraje": 30000}])
    assert posibles_duplicados(d) == {"a": "b", "b": "a"}


def test_estado_general():
    ok = [{"etapa": e, "estado": "ok"} for e in ["busqueda", "descarga", "consolidacion", "analisis"]]
    assert estado_general(ok, False)[0] == "ok"
    assert estado_general([], True)[0] == "pendiente"          # 8:00 aún corriendo
    assert estado_general([], False)[0] == "error"             # no hubo ejecución
    assert estado_general(ok[:2], True)[0] == "parcial"        # a medias
    assert estado_general(ok[:3] + [{"etapa": "analisis", "estado": "error"}], False)[0] == "error"
