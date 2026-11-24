"""Genera docs/Documento_Taller2.pdf: una página con diagrama de arquitectura y decisiones."""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph
from reportlab.pdfgen import canvas

SALIDA = Path(__file__).with_name("Documento_Taller2.pdf")
W, H = letter
M = 36  # margen

c = canvas.Canvas(str(SALIDA), pagesize=letter)
c.setTitle("Taller 2 — Monitoreo Toyota Corolla en Carroya")

# Título
c.setFont("Helvetica-Bold", 13)
c.drawString(M, H - M - 4, "Taller 2 · Monitoreo automático de anuncios de Toyota Corolla 2022–2026 (Carroya)")
c.setFont("Helvetica", 8)
c.setFillColor(colors.HexColor("#444444"))
c.drawString(M, H - M - 16, "Taller de Python · Uniandes · Jair Acevedo · Dayanna Reyes · "
             "repo: github.com/jairesacevedo/busqueda-corolla · período: 16–21 nov 2026 (America/Bogota)")
c.setFillColor(colors.black)

# ---------------------------------------------------------------- diagrama
top = H - M - 30
box_h, gap = 46, 9
azul, gris, verde = colors.HexColor("#dbeafe"), colors.HexColor("#f3f4f6"), colors.HexColor("#dcfce7")


def caja(x, y, w, h, titulo, sub, fondo):
    c.setFillColor(fondo)
    c.setStrokeColor(colors.HexColor("#555555"))
    c.roundRect(x, y, w, h, 5, fill=1, stroke=1)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 7.5)
    c.drawCentredString(x + w / 2, y + h - 11, titulo)
    c.setFont("Helvetica", 6.3)
    for i, linea in enumerate(sub):
        c.drawCentredString(x + w / 2, y + h - 21 - i * 7.5, linea)


def flecha(x1, y1, x2, y2):
    c.setStrokeColor(colors.HexColor("#333333"))
    c.line(x1, y1, x2, y2)
    c.setFillColor(colors.HexColor("#333333"))
    c.wedge(x2 - 7, y2 - 4, x2 + 1, y2 + 4, 160, 40, fill=1, stroke=0) if False else None
    p = c.beginPath()
    p.moveTo(x2, y2); p.lineTo(x2 - 5, y2 + 3); p.lineTo(x2 - 5, y2 - 3); p.close()
    c.drawPath(p, fill=1, stroke=0)


# Marco GitHub Actions 8:00
c.setStrokeColor(colors.HexColor("#2563eb")); c.setDash(3, 2)
c.roundRect(M, top - 92, 418, 84, 6, stroke=1, fill=0)
c.roundRect(M + 426, top - 92, W - 2 * M - 426, 84, 6, stroke=1, fill=0)
c.setDash()
c.setFont("Helvetica-Bold", 7); c.setFillColor(colors.HexColor("#2563eb"))
c.drawString(M + 6, top - 18, "GitHub Actions · diario.yml · 8:00 (máquina Ubuntu temporal)")
c.drawString(M + 432, top - 18, "correo.yml · 11:00")
c.setFillColor(colors.black)

bw, by = 74, top - 78
nombres = [("1. Búsqueda", ["POST find-filters", "todas las páginas", "verifica criterios"]),
           ("2. Descarga", ["GET detalle/{uuid}", "3 reintentos", "enlaces + datos CSV"]),
           ("3. Consolidación", ["SQLite idempotente", "sha256 + UPSERT", "disponibilidad"]),
           ("4. Análisis", ["distribución + PNG", "comparables", "gangas + duplicados"]),
           ("5. commit/push", ["datos, base, logs", "y reportes", "al repositorio"])]
x = M + 8
for i, (t, s) in enumerate(nombres):
    caja(x, by, bw, box_h, t, s, verde if i == 4 else azul)
    if i < 4:
        flecha(x + bw, by + box_h / 2, x + bw + gap - 1, by + box_h / 2)
    x += bw + gap - 1
caja(M + 434, by, W - 2 * M - 442, box_h, "6. Correo HTML (Gmail)",
     ["lee log + reportes del repo", "estado, cifras, gráfica, gangas", "se envía siempre · copia .eml"], azul)
flecha(M + 418, by + box_h / 2, M + 433, by + box_h / 2)

c.setFont("Helvetica-Oblique", 7)
c.drawCentredString(W / 2, top - 102, "Flujo de datos: API Carroya → datos/diarios/AAAA-MM-DD (enlaces + datos) → "
                    "datos/corolla.db → reportes/AAAA-MM-DD → correo")
c.drawCentredString(W / 2, top - 111, "Cada etapa escribe una fila en logs/log_ejecuciones.csv · "
                    "la contraseña de Gmail es un secret del repositorio")

# ---------------------------------------------------------------- texto en dos columnas
st = ParagraphStyle("t", fontName="Helvetica", fontSize=8.9, leading=11.2, spaceAfter=5)
sh = ParagraphStyle("h", parent=st, fontName="Helvetica-Bold", fontSize=9.3, spaceAfter=2,
                    textColor=colors.HexColor("#1e3a8a"))
col_w = (W - 2 * M - 14) / 2

izq = [
    ("Funcionamiento", "Carroya arma su página con JavaScript; los datos vienen de una API pública, así que no se usa "
     "Selenium. <b>GitHub Actions</b> enciende una máquina temporal, descarga el repo (que trae los datos de días "
     "anteriores), ejecuta el pipeline y hace <i>commit</i> de los resultados: el repositorio es a la vez código, "
     "programador de tareas, almacenamiento y evidencia. No requiere ningún computador encendido; sí requiere el "
     "repo activo, el <i>secret</i> GMAIL_APP_PASSWORD y que la API conserve su formato."),
    ("Recolección e identificación", "Se recorren las páginas hasta una vacía. La búsqueda es <b>completa</b> si "
     "todas las páginas responden y los anuncios únicos cuadran con <i>count</i>. Identificador estable: el "
     "<b>UUID de Carroya</b>, que es parte de la URL; volver a encontrar un anuncio no crea uno nuevo. Archivos "
     "diarios con estados <i>sin intentar / descargado / fallido</i> y su motivo; un faltante queda vacío, nunca en "
     "cero. No se guardan datos del vendedor (lista blanca). <b>Posible mismo vehículo</b>: igual año, versión, "
     "color y ciudad, con km a menos de 2 %; solo se reporta (no hay placa completa)."),
    ("Almacenamiento: SQLite", "Tablas <i>anuncios</i> (ficha más reciente, primera y última vez visto, "
     "disponibilidad), <i>observaciones</i> (anuncio×día), <i>cambios</i> (antes→después) y "
     "<i>archivos_procesados</i>. Frente a <b>CSV</b>: SQL, llaves y UPSERT nativos, todo en un archivo; pero es "
     "binario y no se abre en Excel. Frente a <b>Parquet</b>: transacciones y llaves, aunque es menos eficiente "
     "en análisis columnar. Se compensa exportando las tablas a CSV cada día."),
]
der = [
    ("Actualización", "Idempotente: la huella <b>sha256</b> evita reprocesar un archivo; UPSERT por (id, fecha); los "
     "cambios se miden contra la última descarga anterior y la ficha se recalcula desde las observaciones. "
     "<b>encontrado</b> = apareció (aunque falle el detalle); <b>no_encontrado</b> = ausente en una búsqueda "
     "completa (no implica vendido); <b>desconocido</b> = ausente en una búsqueda incompleta."),
    ("Detección de gangas", "Una observación válida por anuncio y día; se excluyen precios faltantes, menores de "
     "$20 M o mayores de $400 M. Cada precio se compara con la <b>mediana de comparables</b> (mínimo 5): mismo año, "
     "combustible y banda de km; si no alcanza, mismo año y combustible; luego año ±1. <b>Alerta</b> si el precio es "
     "≤ 85 % de la mediana <b>y</b> menor que Q1. Cada alerta trae su explicación; si no hay comparables se "
     "reporta “datos insuficientes”. Solo se alertan los anuncios nuevos. Límites: el precio publicado no es el "
     "de venta, hay pocos datos y puede haber duplicados o errores de digitación."),
    ("Automatización y resultados", "Crons a las 7:40 y 10:40; el script espera las 8:00:00 y 11:00:00 y "
     "<i>--una-vez</i> evita duplicar. Los 6 días se completaron: entre 60 y 62 enlaces por día, 0 descargas "
     "fallidas, <b>64 anuncios únicos</b>, 379 observaciones, 3 posibles gangas el 16-nov (2 son un mismo carro "
     "publicado dos veces) y 6 correos enviados. <b>Incidencia:</b> GitHub arrancó los crons con <b>6 a 10 h de "
     "retraso</b> (recolección entre 14:47 y 17:30; correo entre 16:07 y 18:50). Con hora estricta, hace falta "
     "un disparador externo (diseñado, no configurado a tiempo) o un servidor propio. Detalle en el README."),
]


def columna(x, bloques):
    y = top - 124
    for titulo, texto in bloques:
        for estilo, contenido in ((sh, titulo), (st, texto)):
            p = Paragraph(contenido, estilo)
            _, h = p.wrap(col_w, 1000)
            p.drawOn(c, x, y - h)
            y -= h + estilo.spaceAfter
    return y


y1 = columna(M, izq)
y2 = columna(M + col_w + 14, der)

# ---------------------------------------------------------------- tabla de resultados
from reportlab.platypus import Table, TableStyle  # noqa: E402
filas = [["Día", "Enlaces", "Descargas ok / fallidas", "Nuevos", "Gangas nuevas", "Mediana",
          "Inicio recolección", "Envío correo"],
         ["16-nov", "61", "61 / 0", "61", "3", "$105,9 M", "17:30", "18:50"],
         ["17-nov", "60", "60 / 0", "1", "0", "$106,4 M", "16:20", "18:09"],
         ["18-nov", "62", "62 / 0", "2", "0", "$106,4 M", "15:53", "17:41"],
         ["19-nov", "61", "61 / 0", "0", "0", "$106,9 M", "15:58", "17:45"],
         ["20-nov", "61", "61 / 0", "0", "0", "$106,9 M", "15:43", "17:21"],
         ["21-nov", "61", "61 / 0", "0", "0", "$106,9 M", "14:47", "16:07"]]
t = Table(filas, colWidths=[44, 46, 96, 44, 66, 60, 90, 74], rowHeights=12)
t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 7.6),
                       ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7.6),
                       ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbeafe")),
                       ("TEXTCOLOR", (6, 1), (7, -1), colors.HexColor("#b91c1c")),
                       ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")),
                       ("ALIGN", (1, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
tw, th = t.wrap(0, 0)
yt = min(y1, y2) - 14
c.setFont("Helvetica-Bold", 9.3); c.setFillColor(colors.HexColor("#1e3a8a"))
c.drawString(M, yt, "Resultados del período (horas reales en America/Bogota; en rojo, fuera del horario 8:00/11:00)")
c.setFillColor(colors.black)
t.drawOn(c, M, yt - 6 - th)
y1 = y2 = yt - 6 - th
assert min(y1, y2) > M, f"El texto no cabe en una página: y={min(y1, y2):.0f}"
c.showPage()
c.save()
print(SALIDA, "· espacio libre inferior:", round(min(y1, y2) - M))
