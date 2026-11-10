"""Sonda de conectividad: comprueba si este equipo (p. ej. un runner de GitHub Actions)
puede consultar la API de búsqueda y de detalle de Carroya. No guarda datos."""
import sys
import requests

API = "https://carroya-habilitadora-api.avaldigitallabs.com"
HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (taller-python-uniandes; monitoreo academico)",
    "Origin": "https://www.carroya.com",
    "Referer": "https://www.carroya.com/",
}


def buscar(pagina: int) -> dict:
    cuerpo = {
        "isReqForRedirect": False,
        "params": {
            "brand": "Toyota",
            "category": "Automóviles y Camionetas",
            "model": "Corolla",
            "modelRange": "2022-2026",
            "page": str(pagina),
        },
        "seoArray": [],
    }
    r = requests.post(f"{API}/find-filters", json=cuerpo, headers=HEADERS, timeout=30)
    print(f"find-filters página {pagina}: HTTP {r.status_code}")
    r.raise_for_status()
    return r.json()


def main() -> int:
    try:
        j = buscar(1)
        print(f"count={j.get('count')} pages={j.get('pages')}")
        res = j.get("results", {})
        ids = []
        for lista in ("superHighlights", "megaHighlights", "latestReleases"):
            ids += [a["id"] for a in res.get(lista) or [] if "id" in a]
        print(f"anuncios en página 1: {len(ids)}")
        if ids:
            r = requests.get(f"{API}/find-vehicle-detail/{ids[0]}", headers=HEADERS, timeout=30)
            d = r.json().get("data", {})
            print(f"detalle {ids[0]}: HTTP {r.status_code} | año={d.get('year')} precio={d.get('price')}")
        print("RESULTADO: OK, la API es accesible desde este equipo")
        return 0
    except Exception as e:  # la sonda solo informa
        print(f"RESULTADO: FALLO -> {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
