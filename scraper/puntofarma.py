"""Scraper de Punto Farma (Next.js App Router).

CORRECCION A LA INVESTIGACION INICIAL: **no hace falta Playwright.** El plan lo
daba por client-side porque usa React Server Components, pero el RSC se
serializa DENTRO del HTML: la ficha llega con los precios ya renderizados, mas
un JSON-LD `Product` (sku, gtin, marca) y un `BreadcrumbList` con la ruta
completa de categorias. httpx alcanza.

⚠️ El `price` del JSON-LD es el precio de LISTA, no el vigente: ignora el
"precio exclusivo para compras via Web". El precio real sale del HTML. Es la
misma trampa que en Farmacenter, y por eso se cruzan las dos fuentes.

robots.txt solo prohibe carrito, mi-cuenta, compra-finalizada y una ficha
puntual de vacuna; el catalogo esta permitido y no declara Crawl-delay.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterator

from selectolax.parser import HTMLParser

from .base import ClienteHTTP, Limite
from .db import ProductoScrapeado, conectar, guardar, marcar_bajas

SLUG = "puntofarma"
BASE = "https://www.puntofarma.com.py"
SITEMAP = f"{BASE}/sitemap.xml"

# No declara Crawl-delay, pero las fichas pesan ~580 KB: 2 req/s ya es mucho
# ancho de banda del lado de ellos.
LIMITE = Limite(req_por_seg=2.0, concurrencia=2)
TAM_LOTE = 500

# Id de la categoria raiz "Medicamentos" (https://.../categoria/1/medicamentos).
RAIZ_MEDICAMENTOS = "1"

# robots.txt prohibe explicitamente esta ficha; se excluye por URL.
BLOQUEADAS = ("/producto/194778/",)

RE_LOC = re.compile(r"<loc>(.*?)</loc>")
RE_LD_JSON = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
RE_CAT_ID = re.compile(r"/categoria/(\d+)/")
RE_PCT = re.compile(r"-<!-- -->(\d+)<!-- -->%")


def _guaranies(texto: str) -> float | None:
    digitos = re.sub(r"[^\d]", "", texto)
    return float(digitos) if digitos else None


def _bloques_ld(html: str) -> list[dict]:
    salida = []
    for bloque in RE_LD_JSON.findall(html):
        try:
            d = json.loads(bloque)
        except json.JSONDecodeError:
            continue
        if isinstance(d, dict):
            salida.append(d)
    return salida


def ruta_categorias(bloques: list[dict]) -> tuple[str | None, str | None]:
    """Devuelve (ruta legible, id de la categoria raiz) desde el BreadcrumbList."""
    for d in bloques:
        if d.get("@type") != "BreadcrumbList":
            continue
        items = d.get("itemListElement") or []
        # position 1 es "Inicio"; la categoria raiz real es la 2.
        nombres = [i.get("name") for i in items[1:] if i.get("name")]
        raiz_id = None
        for i in items[1:]:
            if m := RE_CAT_ID.search(str(i.get("item") or "")):
                raiz_id = m.group(1)
                break
        return (" > ".join(nombres) if nombres else None), raiz_id
    return None, None


def clasificar_condicion(raiz_id: str | None) -> str:
    """Falla cerrado: sin categoria conocida, se asume bajo receta.

    Punto Farma no declara la condicion de venta en la ficha. Todo lo que cuelga
    de "Medicamentos" — y todo lo que no se pudo clasificar — sale sin precio.
    Mostrar de mas el precio de un Rx viola la Ley 1119/97 Art. 25; ocultar de
    mas solo pierde una ficha, y T5 lo va a recuperar.
    """
    if raiz_id is None or raiz_id == RAIZ_MEDICAMENTOS:
        return "bajo_receta"
    return "no_medicamento"


def parsear_ficha(url: str, html: str) -> ProductoScrapeado | None:
    bloques = _bloques_ld(html)
    producto = next((d for d in bloques if d.get("@type") == "Product"), None)
    if producto is None:
        return None

    arbol = HTMLParser(html)

    # <del class="precio-sin-descuento"> = lista.
    nodo_lista = arbol.css_first("del.precio-sin-descuento")
    lista = _guaranies(nodo_lista.text()) if nodo_lista is not None else None

    # El precio vigente vive en el bloque "Con descuento".
    oferta = None
    bloque_dto = arbol.css_first("div.precio-con-descuento")
    if bloque_dto is not None:
        for span in bloque_dto.css("span"):
            if (v := _guaranies(span.text())) is not None:
                oferta = v
                break

    if oferta is None:
        # Sin descuento web, el JSON-LD y el precio mostrado coinciden.
        precio_ld = (producto.get("offers") or {}).get("price")
        oferta = float(precio_ld) if precio_ld else None
        lista = None
    if lista is not None and oferta is not None and lista <= oferta:
        lista = None

    pct = None
    if m := RE_PCT.search(html):
        pct = float(m.group(1))
    elif lista and oferta:
        pct = round((lista - oferta) / lista * 100, 2)

    ruta, raiz_id = ruta_categorias(bloques)
    ean = str(producto.get("gtin") or "").strip()
    marca = producto.get("brand")

    return ProductoScrapeado(
        sku_farmacia=str(producto.get("sku") or "").strip(),
        nombre=(producto.get("name") or "").strip(),
        url_producto=url,
        condicion_venta=clasificar_condicion(raiz_id),
        ean=ean if ean.isdigit() else None,
        marca=(marca.get("name") if isinstance(marca, dict) else marca) or None,
        imagen_url=producto.get("image") or None,
        categoria_ruta=ruta,
        precio_lista=lista,
        precio_oferta=oferta,
        descuento_pct=pct,
        campos_extra={"categoria_raiz_id": raiz_id},
    )


def scrapear(limite_urls: int | None = None) -> Iterator[list[ProductoScrapeado]]:
    lote: list[ProductoScrapeado] = []
    with ClienteHTTP(LIMITE, timeout=90.0) as cli:
        resp = cli.get(SITEMAP)
        if resp is None:
            raise RuntimeError("No se pudo leer el sitemap de Punto Farma")
        urls = [
            u for u in RE_LOC.findall(resp.text)
            if "/producto/" in u and not any(b in u for b in BLOQUEADAS)
        ]
        if limite_urls:
            urls = urls[:limite_urls]

        for url in urls:
            pagina = cli.get(url)
            if pagina is None:
                continue
            p = parsear_ficha(url, pagina.text)
            if p is not None and p.sku_farmacia:
                lote.append(p)
            if len(lote) >= TAM_LOTE:
                yield lote
                lote = []
    if lote:
        yield lote


def main() -> None:
    ap = argparse.ArgumentParser(description="Scraper de Punto Farma")
    ap.add_argument("--limite", type=int, help="solo N fichas")
    ap.add_argument("--sin-guardar", action="store_true", help="no escribe en Supabase")
    args = ap.parse_args()

    if args.sin_guardar:
        for lote in scrapear(args.limite):
            for p in lote[:10]:
                print(f"{p.condicion_venta:15} {p.precio_oferta!s:>10} ean={p.ean!s:<14} "
                      f"{(p.categoria_ruta or '-')[:26]:28} {p.nombre[:38]}")
            print(f"-- lote de {len(lote)} --")
        print("(no se escribio en la base)")
        return

    total = {"productos": 0, "precios": 0}
    vistos: list[str] = []
    with conectar() as conn:
        for lote in scrapear(args.limite):
            r = guardar(conn, SLUG, lote, parcial=True)
            total["productos"] += r["productos"]
            total["precios"] += r["precios"]
            vistos.extend(p.sku_farmacia for p in lote)
        bajas = 0 if args.limite else marcar_bajas(conn, SLUG, vistos)

    print(f"[puntofarma] {total | {'bajas': bajas}}")


if __name__ == "__main__":
    main()
