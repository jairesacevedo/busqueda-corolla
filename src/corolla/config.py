"""Configuración común: rutas, zona horaria y criterios de búsqueda."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Bogota")
RAIZ = Path(__file__).resolve().parents[2]

API = "https://carroya-habilitadora-api.avaldigitallabs.com"
HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (taller-python-uniandes; monitoreo academico)",
    "Origin": "https://www.carroya.com",
    "Referer": "https://www.carroya.com/",
}
CRITERIOS = {"marca": "Toyota", "linea": "Corolla", "anio_min": 2022, "anio_max": 2026}
PARAMS_BUSQUEDA = {
    "brand": "Toyota",
    "category": "Automóviles y Camionetas",
    "model": "Corolla",
    "modelRange": "2022-2026",
}
PAUSA_S = float(os.getenv("COROLLA_PAUSA_S", "1.0"))  # cortesía entre peticiones
REINTENTOS = 3
MAX_PAGINAS = 50  # tope de seguridad


def ahora() -> datetime:
    """Hora actual en America/Bogota (con desfase explícito)."""
    return datetime.now(TZ)


def iso(dt: datetime | None) -> str:
    return dt.isoformat(timespec="seconds") if dt else ""


def modo() -> str:
    """'real' o 'prueba'. Por defecto prueba, para no mezclar evidencias por accidente."""
    m = os.getenv("COROLLA_MODO", "prueba").strip().lower()
    if m not in {"real", "prueba"}:
        raise ValueError(f"COROLLA_MODO inválido: {m}")
    return m


def base_dir(m: str | None = None) -> Path:
    """Carpeta raíz de salida: el repo (real) o pruebas/ (prueba)."""
    m = m or modo()
    return RAIZ if m == "real" else RAIZ / "pruebas"


def rutas(fecha: str, m: str | None = None) -> dict[str, Path]:
    b = base_dir(m)
    dia = b / "datos" / "diarios" / fecha
    return {
        "dia": dia,
        "enlaces": dia / f"enlaces_{fecha}.csv",
        "datos": dia / f"datos_{fecha}.csv",
        "meta": dia / f"busqueda_{fecha}.json",
        "db": b / "datos" / "corolla.db",
        "export": b / "datos" / "export",
        "reportes": b / "reportes" / fecha,
        "log": b / "logs" / "log_ejecuciones.csv",
    }
