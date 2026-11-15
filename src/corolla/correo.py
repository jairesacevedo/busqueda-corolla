"""Paso 7: correo diario de las 11:00. Se envía SIEMPRE, aunque falle parte del proceso.

Variables de entorno:
    GMAIL_USER          cuenta que envía (p. ej. jairesacevedo@gmail.com)
    GMAIL_APP_PASSWORD  contraseña de aplicación de Gmail (secret del repositorio; nunca en el código)
    COROLLA_DESTINO     destinatarios separados por coma
    EJECUCION_EN_CURSO  "1" si el workflow de las 8:00 sigue corriendo (lo detecta correo.yml)

Uso:
    python -m corolla.correo --modo real --esperar-hasta 11:00
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import os
import smtplib
import sys
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

import pandas as pd

from . import config as cfg
from .analizar import miles, millones
from .logs import escribir
from .pipeline import esperar_hasta

ETAPAS = ["busqueda", "descarga", "consolidacion", "analisis"]
NOMBRES = {"busqueda": "Búsqueda", "descarga": "Descarga", "consolidacion": "Consolidación",
           "analisis": "Análisis"}
ICONO = {"ok": "✅", "parcial": "⚠️", "omitido": "↩️", "error": "❌", "pendiente": "⏳"}


def leer_log(ruta: Path, fecha: str) -> list[dict]:
    """Filas del log de la última ejecución del pipeline iniciada en esa fecha."""
    if not ruta.exists():
        return []
    with ruta.open(encoding="utf-8") as f:
        filas = [r for r in csv.DictReader(f) if r["inicio"].startswith(fecha) and r["etapa"] in ETAPAS]
    if not filas:
        return []
    ultima = max(filas, key=lambda r: r["inicio"])["id_ejecucion"]
    return [r for r in filas if r["id_ejecucion"] == ultima]


def estado_general(filas: list[dict], en_curso: bool) -> tuple[str, str, dict]:
    por_etapa = {r["etapa"]: r for r in filas}
    estados = {e: por_etapa[e]["estado"] if e in por_etapa else "pendiente" for e in ETAPAS}
    if not filas:
        if en_curso:
            return "pendiente", "La ejecución de las 8:00 sigue en curso: la información de hoy está incompleta.", estados
        return "error", "No hay registro de la ejecución de hoy (no se inició o falló antes de registrar).", estados
    if any(v == "error" for v in estados.values()):
        return "error", "Una o más etapas fallaron. Revise los errores.", estados
    if any(v == "pendiente" for v in estados.values()):
        msg = "La ejecución sigue en curso" if en_curso else "La ejecución no completó todas las etapas"
        return "parcial", msg + ": la información puede estar incompleta.", estados
    if any(v == "parcial" for v in estados.values()):
        return "parcial", "El proceso terminó con advertencias (ver errores).", estados
    return "ok", "El proceso de las 8:00 terminó correctamente.", estados


def _celda(v) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else html.escape(str(v))


def construir(fecha: str, m: str, en_curso: bool) -> tuple[str, str, Path | None, dict]:
    rt = cfg.rutas(fecha, m)
    filas = leer_log(rt["log"], fecha)
    estado, mensaje, por_etapa = estado_general(filas, en_curso)
    reg = {r["etapa"]: r for r in filas}
    g = lambda etapa, campo: reg.get(etapa, {}).get(campo) or "—"  # noqa: E731

    resumen = {}
    if (rt["reportes"] / "resumen.json").exists():
        resumen = json.loads((rt["reportes"] / "resumen.json").read_text(encoding="utf-8"))
    png = rt["reportes"] / "distribucion.png"
    png = png if png.exists() and resumen.get("grafica") else None
    gangas = pd.read_csv(rt["reportes"] / "gangas.csv") if (rt["reportes"] / "gangas.csv").exists() else None
    cambios = (pd.read_csv(rt["reportes"] / "cambios_precio.csv")
               if (rt["reportes"] / "cambios_precio.csv").exists() else None)

    prefijo = "[PRUEBA] " if m == "prueba" else ""
    n_g = 0 if gangas is None else len(gangas)
    asunto = f"{prefijo}Corolla 2022–2026 · reporte {fecha} · {ICONO[estado]} {estado.upper()} · {n_g} posibles gangas"

    errores = [f"<li><b>{NOMBRES.get(r['etapa'], r['etapa'])}:</b> {html.escape(r['errores'])}</li>"
               for r in filas if r.get("errores")]
    pendientes = [NOMBRES[e] for e, v in por_etapa.items() if v == "pendiente"]

    h = [f"""<div style="font-family:Arial,sans-serif;max-width:760px;color:#222">
<h2 style="margin-bottom:4px">{prefijo}Monitoreo Toyota Corolla 2022–2026 · Carroya</h2>
<p style="margin-top:0;color:#555">Reporte del {fecha} · generado {cfg.iso(cfg.ahora())} (America/Bogota)</p>
<div style="padding:10px;border-radius:6px;background:{ {'ok': '#e6ffed', 'parcial': '#fff8e1', 'pendiente': '#fff8e1', 'error': '#ffe6e6'}[estado]}">
<b>Estado general: {ICONO[estado]} {estado.upper()}</b><br>{html.escape(mensaje)}</div>
<h3>1. Resumen del proceso</h3>
<table cellpadding="5" style="border-collapse:collapse" border="1">
<tr><td>Enlaces encontrados</td><td><b>{g('busqueda', 'enlaces_encontrados')}</b></td>
<td>Búsqueda completa</td><td>{ {'True': 'sí', 'False': 'no'}.get(g('busqueda', 'busqueda_completa'), '—')}</td></tr>
<tr><td>Anuncios nuevos (vistos por primera vez)</td><td><b>{g('consolidacion', 'anuncios_nuevos')}</b></td>
<td>Anuncios únicos acumulados</td><td>{g('consolidacion', 'anuncios_unicos_total')}</td></tr>
<tr><td>Descargas exitosas</td><td>{g('descarga', 'descargas_ok')}</td>
<td>Descargas fallidas</td><td>{g('descarga', 'descargas_fallidas')}</td></tr>
<tr><td>Registros actualizados / sin cambio</td>
<td colspan="3">{g('consolidacion', 'registros_actualizados')} / {g('consolidacion', 'registros_sin_cambio')}</td></tr>
</table>
<p>Etapas: {' · '.join(f"{NOMBRES[e]} {ICONO.get(v, '')}" for e, v in por_etapa.items())}</p>
<h3>2. Errores y etapas pendientes</h3>
{('<ul>' + ''.join(errores) + '</ul>') if errores else '<p>Sin errores registrados.</p>'}
{f"<p>Etapas pendientes: {', '.join(pendientes)}.</p>" if pendientes else ''}
<h3>3. Distribución de precios del día</h3>"""]

    st = resumen.get("estadisticas")
    if st:
        h.append(f"""<p>Una observación por anuncio: la descargada hoy con precio válido
(n = <b>{st['n']}</b>; precios inválidos excluidos: {resumen.get('precios_invalidos', 0)}).</p>
<table cellpadding="5" style="border-collapse:collapse" border="1"><tr>
<th>Mínimo</th><th>Q1</th><th>Mediana</th><th>Q3</th><th>Máximo</th></tr><tr>
<td>{millones(st['minimo'])}</td><td>{millones(st['q1'])}</td><td><b>{millones(st['mediana'])}</b></td>
<td>{millones(st['q3'])}</td><td>{millones(st['maximo'])}</td></tr></table>""")
        if resumen.get("por_anio"):
            h.append("<p>Mediana por año: " + " · ".join(
                f"{r['anio']}: {millones(r['median'])} (n={r['count']})" for r in resumen["por_anio"]) + "</p>")
        if png:
            h.append('<img src="cid:grafica" style="max-width:100%" alt="Distribución de precios">')
    else:
        motivo = resumen.get("motivo_sin_analisis") or "El análisis del día no está disponible (ver estado del proceso)."
        h.append(f"<p>No se presenta gráfica ni estadísticas: {html.escape(motivo)}</p>")

    h.append("<h3>4. Posibles gangas entre los anuncios nuevos del día</h3>")
    if gangas is None:
        h.append("<p>No se pudo evaluar: el análisis del día no está disponible.</p>")
    elif gangas.empty:
        h.append(f"<p>No se detectaron posibles gangas entre los anuncios nuevos de hoy "
                 f"({resumen.get('nuevos_validos', 0)} anuncios nuevos evaluables; "
                 f"{resumen.get('datos_insuficientes', 0)} sin comparables suficientes).</p>")
    else:
        h.append('<table cellpadding="5" style="border-collapse:collapse;font-size:13px" border="1">'
                 "<tr><th>Anuncio</th><th>Precio</th><th>Referencia</th><th>Explicación</th></tr>")
        for r in gangas.itertuples(index=False):
            dup = (f"<br><i>Posible mismo vehículo que otro anuncio ({_celda(r.posible_duplicado_de)})</i>"
                   if isinstance(r.posible_duplicado_de, str) else "")
            km = f"{miles(r.kilometraje)} km" if pd.notna(r.kilometraje) else "km sin dato"
            h.append(f"<tr><td><a href='{_celda(r.url)}'>Corolla {int(r.anio)} {_celda(r.version)}</a><br>"
                     f"{km} · {_celda(r.transmision)} · {_celda(r.combustible)} · {_celda(r.ciudad)} · "
                     f"sunroof: {_celda(r.sunroof) or 'sin dato'}</td>"
                     f"<td><b>{millones(r.precio)}</b></td>"
                     f"<td>Mediana {millones(r.mediana_ref)} · Q1 {millones(r.q1_ref)}<br>"
                     f"{_celda(r.referencia)} (n={int(r.n_comparables)})</td>"
                     f"<td>{_celda(r.explicacion)}{dup}</td></tr>")
        h.append("</table>")
    h.append(f"""<p style="font-size:12px;color:#555">Regla: posible ganga si el precio es ≤ {resumen.get('umbral', 0.85):.0%}
de la mediana de su grupo de comparables <b>y</b> menor que su cuartil inferior; mínimo
{resumen.get('min_comparables', 5)} comparables (mismo año, combustible y banda de km; si no alcanza, se amplía).
"Nuevo" = observado por primera vez por este sistema, no necesariamente publicado hoy.</p>""")

    if cambios is not None and not cambios.empty:
        h.append("<h3>5. Cambios de precio detectados hoy</h3><ul>")
        for r in cambios.itertuples(index=False):
            h.append(f"<li><a href='{_celda(r.url)}'>Corolla {_celda(r.anio)} {_celda(r.version)}</a>: "
                     f"{millones(float(r.valor_anterior))} → {millones(float(r.valor_nuevo))} "
                     f"(desde {_celda(r.fecha_referencia)})</li>")
        h.append("</ul>")
    h.append("<p style='font-size:12px;color:#888'>Taller 2 · Taller de Python · Uniandes. "
             "Datos: carroya.com. Repositorio: github.com/jairesacevedo/busqueda-corolla</p></div>")
    return asunto, "\n".join(h), png, reg


def enviar(asunto: str, cuerpo_html: str, png: Path | None, guardar_en: Path) -> str:
    usuario = os.getenv("GMAIL_USER", "").strip()
    clave = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
    destino = [d.strip() for d in os.getenv("COROLLA_DESTINO", "").split(",") if d.strip()]

    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = asunto, usuario or "sin-remitente", ", ".join(destino)
    msg["Date"] = formatdate(localtime=False)
    msg.set_content("Este reporte requiere un cliente de correo con HTML.")
    msg.add_alternative(cuerpo_html, subtype="html")
    if png:
        msg.get_payload()[1].add_related(png.read_bytes(), "image", "png", cid="<grafica>")
    guardar_en.mkdir(parents=True, exist_ok=True)
    (guardar_en / "correo.eml").write_bytes(bytes(msg))  # copia de evidencia
    (guardar_en / "correo.html").write_text(cuerpo_html, encoding="utf-8")

    faltan = [n for n, v in (("GMAIL_USER", usuario), ("GMAIL_APP_PASSWORD", clave),
                             ("COROLLA_DESTINO", destino)) if not v]
    if faltan:
        return "error: faltan variables " + ", ".join(faltan)
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
            s.login(usuario, clave)
            s.send_message(msg)
        return "enviado"
    except Exception as e:
        return f"error: {type(e).__name__}: {e}"[:300]


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--modo", choices=["real", "prueba"], default=os.getenv("COROLLA_MODO", "prueba"))
    p.add_argument("--fecha")
    p.add_argument("--esperar-hasta")
    a = p.parse_args(argv)
    os.environ["COROLLA_MODO"] = a.modo
    if a.esperar_hasta:
        esperar_hasta(a.esperar_hasta)
    inicio = cfg.ahora()
    fecha = a.fecha or inicio.date().isoformat()
    en_curso = os.getenv("EJECUCION_EN_CURSO", "0") == "1"
    rt = cfg.rutas(fecha, a.modo)
    run = ("PRUEBA-" if a.modo == "prueba" else "") + "CORREO-" + inicio.strftime("%Y%m%d-%H%M%S")

    try:
        asunto, cuerpo, png, reg = construir(fecha, a.modo, en_curso)
    except Exception as e:  # incluso si el reporte falla, se envía un correo mínimo
        asunto = f"{'[PRUEBA] ' if a.modo == 'prueba' else ''}Corolla · reporte {fecha} · ❌ ERROR"
        cuerpo = (f"<p>No se pudo construir el reporte del {fecha}.</p>"
                  f"<p>Error: {html.escape(f'{type(e).__name__}: {e}')}</p>")
        png, reg = None, {}
    estado = enviar(asunto, cuerpo, png, rt["reportes"])
    print(f"Correo: {estado} · {asunto}", flush=True)
    escribir(rt["log"], {"id_ejecucion": run, "modo": a.modo, "etapa": "correo",
                         "inicio": cfg.iso(inicio), "fin": cfg.iso(cfg.ahora()),
                         "duracion_s": round((cfg.ahora() - inicio).total_seconds(), 1),
                         "estado": "ok" if estado == "enviado" else "error",
                         "errores": "" if estado == "enviado" else estado, "estado_correo": estado})
    return 0 if estado == "enviado" else 1


if __name__ == "__main__":
    sys.exit(main())
