"""Paso 6: distribución diaria de precios y detección de posibles gangas.

Distribución: una observación por anuncio = la descargada ese día con precio válido.

Método (comparables con jerarquía). Para cada anuncio se busca el grupo de referencia más
específico con al menos MIN_COMPARABLES anuncios del mismo día (sin contarse a sí mismo):
    1. mismo año + mismo combustible + misma banda de kilometraje
    2. mismo año + mismo combustible
    3. año ±1 + mismo combustible
Si ninguno alcanza el mínimo -> "datos insuficientes" (no se evalúa).

Regla: posible ganga si  precio <= UMBRAL x mediana del grupo  Y  precio < Q1 del grupo.
Solo se alertan en el correo los anuncios NUEVOS del día (primera vez vistos por el sistema).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

UMBRAL = 0.85
MIN_COMPARABLES = 5
PRECIO_MIN, PRECIO_MAX = 20_000_000, 400_000_000
BANDAS_KM = [(25_000, "0-25 mil km"), (50_000, "25-50 mil km"), (100_000, "50-100 mil km")]

NIVELES = [
    ("mismo año, combustible y banda de km",
     lambda f, o: (o.anio == f.anio) & (o.combustible == f.combustible) & (o.banda_km == f.banda_km)),
    ("mismo año y combustible",
     lambda f, o: (o.anio == f.anio) & (o.combustible == f.combustible)),
    ("año ±1 y mismo combustible",
     lambda f, o: ((o.anio - f.anio).abs() <= 1) & (o.combustible == f.combustible)),
]


def millones(x) -> str:
    return f"${x / 1e6:,.1f} M".replace(",", "X").replace(".", ",").replace("X", ".")


def miles(x) -> str:
    return f"{x:,.0f}".replace(",", ".")


def banda_km(km):
    if pd.isna(km):
        return None
    for tope, nombre in BANDAS_KM:
        if km <= tope:
            return nombre
    return "más de 100 mil km"


def cargar_dia(ruta_db: Path, fecha: str) -> pd.DataFrame:
    con = sqlite3.connect(ruta_db)
    try:
        return pd.read_sql_query(
            """SELECT o.*, a.url, a.primera_vez_visto
               FROM observaciones o JOIN anuncios a USING (id_anuncio)
               WHERE o.fecha = ? AND o.disponibilidad = 'encontrado'""", con, params=(fecha,))
    finally:
        con.close()


def cambios_precio(ruta_db: Path, fecha: str) -> pd.DataFrame:
    con = sqlite3.connect(ruta_db)
    try:
        return pd.read_sql_query(
            """SELECT c.id_anuncio, a.url, a.anio, a.version, c.valor_anterior, c.valor_nuevo,
                      c.fecha_referencia
               FROM cambios c JOIN anuncios a USING (id_anuncio)
               WHERE c.fecha = ? AND c.campo = 'precio'""", con, params=(fecha,))
    finally:
        con.close()


def _explicar(f, grupo, nivel, med, q1) -> str:
    pct = 1 - f.precio / med
    detalle = [str(int(f.anio)), str(f.combustible).lower()]
    if pd.notna(f.kilometraje):
        detalle.append(f"{miles(f.kilometraje)} km")
    if pd.notna(f.transmision):
        detalle.append(str(f.transmision).lower())
    if pd.notna(f.version):
        detalle.append(f"versión {f.version}")
    sr = {"si": "con sunroof", "no": "sin sunroof"}.get(f.sunroof)
    if sr:
        detalle.append(sr)
    lado = "por debajo" if pct > 0 else "por encima"
    return (f"Corolla {', '.join(detalle)}: {millones(f.precio)} frente a una mediana de {millones(med)} "
            f"en {len(grupo)} comparables ({nivel}); está {abs(pct):.0%} {lado} de la mediana "
            f"y el cuartil inferior del grupo es {millones(q1)}.")


def evaluar(validos: pd.DataFrame) -> pd.DataFrame:
    filas = []
    for f in validos.itertuples(index=False):
        otros = validos[validos.id_anuncio != f.id_anuncio]
        res = {"id_anuncio": f.id_anuncio, "referencia": "datos insuficientes", "n_comparables": 0,
               "mediana_ref": None, "q1_ref": None, "pct_bajo_mediana": None, "posible_ganga": False,
               "explicacion": f"Sin al menos {MIN_COMPARABLES} comparables en ningún nivel: no se evalúa."}
        if pd.notna(f.anio) and pd.notna(f.combustible):
            for nivel, cond in NIVELES:
                grupo = otros[cond(f, otros)]
                if len(grupo) >= MIN_COMPARABLES:
                    med, q1 = grupo.precio.median(), grupo.precio.quantile(0.25)
                    res.update(referencia=nivel, n_comparables=len(grupo), mediana_ref=med, q1_ref=q1,
                               pct_bajo_mediana=round(1 - f.precio / med, 4),
                               posible_ganga=bool(f.precio <= UMBRAL * med and f.precio < q1),
                               explicacion=_explicar(f, grupo, nivel, med, q1))
                    break
        else:
            res["explicacion"] = "Falta el año o el combustible: no se puede formar un grupo comparable."
        filas.append(res)
    return pd.DataFrame(filas)


def posibles_duplicados(df: pd.DataFrame) -> dict[str, str]:
    """Mismo vehículo en anuncios distintos (criterio aproximado, solo se reporta):
    mismo año, versión, color y ciudad, y kilometraje que difiere menos de 2 %.
    Limitación: sin placa completa puede haber falsos positivos (dos carros muy parecidos)."""
    pares: dict[str, list[str]] = {}
    filas = list(df.itertuples(index=False))
    for i, a in enumerate(filas):
        for b in filas[i + 1:]:
            if (a.anio == b.anio and a.version == b.version and a.color == b.color and a.ciudad == b.ciudad
                    and pd.notna(a.kilometraje) and pd.notna(b.kilometraje)
                    and abs(a.kilometraje - b.kilometraje) <= 0.02 * max(a.kilometraje, b.kilometraje, 1)):
                pares.setdefault(a.id_anuncio, []).append(b.id_anuncio)
                pares.setdefault(b.id_anuncio, []).append(a.id_anuncio)
    return {k: "; ".join(v) for k, v in pares.items()}


def grafica(validos: pd.DataFrame, fecha: str, ruta: Path) -> None:
    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    p = validos.precio / 1e6
    ax[0].hist(p, bins=min(15, max(5, len(p) // 4)), color="#2b6cb0", edgecolor="white")
    for q, ls in ((p.quantile(.25), ":"), (p.median(), "-"), (p.quantile(.75), ":")):
        ax[0].axvline(q, color="#c53030", ls=ls, lw=1.2)
    ax[0].set(title=f"Precios publicados — {fecha} (n={len(p)})", xlabel="Millones de pesos",
              ylabel="Anuncios")
    anios = sorted(validos.anio.dropna().unique())
    ax[1].boxplot([validos.loc[validos.anio == a, "precio"] / 1e6 for a in anios],
                  tick_labels=[str(int(a)) for a in anios])
    ax[1].set(title="Precio por año del modelo", xlabel="Año", ylabel="Millones de pesos")
    fig.text(0.01, 0.01, "Línea roja continua: mediana; punteadas: Q1 y Q3", fontsize=8, color="#555")
    fig.tight_layout()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(ruta, dpi=110)
    plt.close(fig)


def analizar(ruta_db: Path, fecha: str, carpeta: Path) -> dict:
    carpeta.mkdir(parents=True, exist_ok=True)
    obs = cargar_dia(ruta_db, fecha)
    desc = obs[obs.estado_descarga == "descargado"].copy()
    invalido = desc.precio.isna() | ~desc.precio.between(PRECIO_MIN, PRECIO_MAX) | (desc.moneda != "PESO")
    validos = desc[~invalido].copy()
    validos["banda_km"] = validos.kilometraje.apply(banda_km)
    validos["nuevo"] = validos.primera_vez_visto == fecha

    resumen = {"fecha": fecha, "encontrados": int(len(obs)), "descargados": int(len(desc)),
               "precios_invalidos": int(invalido.sum()), "n_validos": int(len(validos)),
               "nuevos_validos": int(validos.nuevo.sum()), "umbral": UMBRAL,
               "min_comparables": MIN_COMPARABLES, "grafica": None, "estadisticas": None,
               "motivo_sin_analisis": None}

    if len(validos) < 5:
        resumen["motivo_sin_analisis"] = (f"Solo hay {len(validos)} anuncios con precio válido descargado hoy; "
                                          "no alcanza para una distribución ni para comparar.")
        ev = pd.DataFrame(columns=["id_anuncio", "posible_ganga"])
    else:
        p = validos.precio
        resumen["estadisticas"] = {"n": int(len(p)), "minimo": float(p.min()), "q1": float(p.quantile(.25)),
                                   "mediana": float(p.median()), "q3": float(p.quantile(.75)),
                                   "maximo": float(p.max()), "promedio": float(p.mean())}
        resumen["por_anio"] = (validos.groupby("anio").precio.agg(["count", "median"])
                               .reset_index().astype({"anio": int}).to_dict("records"))
        grafica(validos, fecha, carpeta / "distribucion.png")
        resumen["grafica"] = "distribucion.png"
        ev = evaluar(validos)

    tabla = validos.merge(ev, on="id_anuncio", how="left") if len(ev) else validos.assign(posible_ganga=False)
    tabla["posible_duplicado_de"] = tabla.id_anuncio.map(posibles_duplicados(validos))
    cols = ["id_anuncio", "url", "anio", "version", "precio", "kilometraje", "transmision", "combustible",
            "ciudad", "color", "sunroof", "nuevo", "referencia", "n_comparables", "mediana_ref", "q1_ref",
            "pct_bajo_mediana", "posible_ganga", "posible_duplicado_de", "explicacion"]
    tabla = tabla.reindex(columns=cols)
    tabla.to_csv(carpeta / "evaluacion.csv", index=False)
    gangas = tabla[(tabla.posible_ganga == True) & (tabla.nuevo == True)]  # noqa: E712
    gangas.to_csv(carpeta / "gangas.csv", index=False)

    resumen["gangas_totales"] = int((tabla.posible_ganga == True).sum())  # noqa: E712
    resumen["gangas_nuevas"] = int(len(gangas))
    resumen["posibles_duplicados"] = int(tabla.posible_duplicado_de.notna().sum())
    resumen["datos_insuficientes"] = int((tabla.referencia == "datos insuficientes").sum())
    resumen["por_nivel"] = tabla.referencia.value_counts(dropna=False).to_dict() if len(ev) else {}
    cp = cambios_precio(ruta_db, fecha)
    cp.to_csv(carpeta / "cambios_precio.csv", index=False)
    resumen["cambios_precio"] = int(len(cp))
    (carpeta / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2, default=str),
                                          encoding="utf-8")
    return resumen
