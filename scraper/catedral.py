"""Scraper de Farmacia Catedral (Laravel + Vue).

CORRECCION A LA INVESTIGACION INICIAL: **no hace falta Playwright.** El plan
asumia que los precios se renderizaban del lado del cliente. Es cierto para los
LISTADOS de categoria (llegan vacios), pero las FICHAS son server-rendered:
traen JSON-LD con sku y precio, el bloque `.precio-web` con precio vigente y
tachado, y `window.rutas.categoria` con la categoria y su padre.

Asi que se recorre por sitemap de productos (10.699 fichas) con httpx, igual
que Farmacenter. Sin navegador: menos dependencias, menos memoria y un workflow
de CI mucho mas barato.

Restricciones de su robots.txt, que se respetan al pie de la letra:
  · `Crawl-delay: 1`  -> LIMITE es de 1 req/s, no mas.
  · `Disallow: /api/` -> nunca se toca. Todo sale del HTML publico.

Regalo inesperado: cada ficha publica `tieneDescuentoFormaPago`, un JSON con los
descuentos por medio de pago (porcentaje, dia, fechas, reintegro). Se guarda
crudo en campos_extra: es exactamente el insumo que necesita el detector de
promos bancarias de T13.
"""

from __future__ import annotations

import argparse
import json
import re
from html import unescape
from collections.abc import Iterator

from selectolax.parser import HTMLParser

from .base import ClienteHTTP, Limite
from .db import ProductoScrapeado, conectar, guardar, marcar_bajas

SLUG = "catedral"
BASE = "https://www.farmaciacatedral.com.py"
SITEMAP_PRODUCTOS = f"{BASE}/sitemap-products.xml"
SITEMAP_CATEGORIAS = f"{BASE}/sitemap-categories.xml"

# Su robots.txt pide Crawl-delay: 1. No se sube de ahi aunque el sitio aguante.
LIMITE = Limite(req_por_seg=1.0, concurrencia=1)
TAM_LOTE = 500

# Id de la categoria raiz "Medicamentos" (verificado: categoria_principal null).
RAIZ_MEDICAMENTOS = 1

RE_LOC = re.compile(r"<loc>(.*?)</loc>")
RE_LD_JSON = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
RE_CATEGORIA_JS = re.compile(r"categoria:\s*(\{.*?\}),\s*marca:", re.S)
RE_EAN_IMAGEN = re.compile(r"/(\d{8,14})-\d+\.(?:png|jpg|jpeg|webp)", re.I)


def _guaranies(texto: str) -> float | None:
    digitos = re.sub(r"[^\d]", "", texto)
    return float(digitos) if digitos else None


def categoria_de_pagina(html: str) -> dict | None:
    """Lee `window.rutas.categoria`, que toda pagina de Catedral publica."""
    m = RE_CATEGORIA_JS.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def mapa_categorias(cli: ClienteHTTP) -> dict[int, int | None]:
    """Devuelve {id_categoria: id_padre} recorriendo el sitemap de categorias.

    Son ~289 peticiones extra, pero sin el arbol no hay forma de saber que
    "Analgesicos y Antipireticos" cuelga de "Medicamentos", y de eso depende
    todo el gate legal. El listado en si llega vacio (es client-side); lo que se
    aprovecha es el `window.rutas.categoria` que igual viene en el HTML.
    """
    resp = cli.get(SITEMAP_CATEGORIAS)
    if resp is None:
        raise RuntimeError("No se pudo leer el sitemap de categorias de Catedral")

    padres: dict[int, int | None] = {}
    for url in RE_LOC.findall(resp.text):
        pagina = cli.get(url)
        if pagina is None:
            continue
        cat = categoria_de_pagina(pagina.text)
        if cat and cat.get("id") is not None:
            padres[int(cat["id"])] = cat.get("categoria_principal")
    return padres


def ids_bajo_medicamentos(padres: dict[int, int | None]) -> set[int]:
    """Ids cuya cadena de padres termina en la raiz Medicamentos."""
    bajo: set[int] = set()
    for cid in padres:
        actual, saltos = cid, 0
        # El tope de saltos evita colgarse si el sitio publica un ciclo.
        while actual is not None and saltos < 20:
            if actual == RAIZ_MEDICAMENTOS:
                bajo.add(cid)
                break
            actual = padres.get(actual)
            saltos += 1
    return bajo


def clasificar_condicion(categoria_id: int | None, medicamentos: set[int]) -> str:
    """Falla cerrado, igual que en las otras farmacias.

    Catedral no declara en la ficha si el producto necesita receta. Sin ese
    dato, todo lo que cuelga de "Medicamentos" — y tambien lo que no se pudo
    clasificar — sale como bajo_receta, o sea sin precio. Mostrar de mas el
    precio de un Rx viola la Ley 1119/97; ocultar de mas solo pierde una ficha,
    y T5 (listado DINAVISA) va a recuperar esos casos.
    """
    if categoria_id is None or categoria_id in medicamentos:
        return "bajo_receta"
    return "no_medicamento"


def _producto_ld(html: str) -> dict | None:
    for bloque in RE_LD_JSON.findall(html):
        try:
            d = json.loads(bloque)
        except json.JSONDecodeError:
            continue
        if isinstance(d, dict) and d.get("@type") == "Product":
            return d
    return None


def descuentos_forma_pago(html: str) -> list:
    """Descuentos por medio de pago que Catedral publica en cada ficha.

    Se guarda crudo, sin interpretar: son datos de terceros (bancos) y ninguna
    promo se publica sin revision humana. Sirve como insumo para T13.
    """
    # El bloque viaja dentro de un atributo HTML, o sea escapado (&quot;). Hay
    # que desescapar antes de buscar, si no el regex nunca engancha.
    texto = unescape(html)
    m = re.search(r'"tieneDescuentoFormaPago":(\[.*?\])(?:,"[a-z_]|\})', texto, re.S)
    if not m:
        return []
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return []


def parsear_ficha(url: str, html: str, medicamentos: set[int]) -> ProductoScrapeado | None:
    ld = _producto_ld(html)
    if ld is None:
        return None

    arbol = HTMLParser(html)
    bloque = arbol.css_first("p.precio-web")
    lista = oferta = None
    if bloque is not None:
        # "Gs. 7.714 <span>Gs. 9.075</span>": el <span> es el precio tachado.
        tachado = bloque.css_first("span")
        texto_lista = tachado.text() if tachado is not None else ""
        entero = bloque.text()
        oferta = _guaranies(entero.replace(texto_lista, ""))
        lista = _guaranies(texto_lista)
    if oferta is None:
        precio_ld = (ld.get("offers") or {}).get("price")
        oferta = float(precio_ld) if precio_ld else None
    if lista is not None and oferta is not None and lista <= oferta:
        lista = None

    cat = categoria_de_pagina(html) or {}
    cat_id = cat.get("id")

    imagen = ld.get("image") or ""
    # El nombre del archivo de imagen empieza con el codigo de barras
    # ("7841056006232-0.png"). Es la unica fuente de EAN de este sitio.
    m_ean = RE_EAN_IMAGEN.search(imagen)

    marca = ld.get("brand")
    return ProductoScrapeado(
        sku_farmacia=str(ld.get("sku") or "").strip(),
        nombre=(ld.get("name") or "").strip(),
        url_producto=url,
        condicion_venta=clasificar_condicion(cat_id, medicamentos),
        ean=m_ean.group(1) if m_ean else None,
        marca=(marca.get("name") if isinstance(marca, dict) else marca) or None,
        imagen_url=imagen or None,
        categoria_ruta=cat.get("nombre"),
        precio_lista=lista,
        precio_oferta=oferta,
        descuento_pct=(round((lista - oferta) / lista * 100, 2) if lista and oferta else None),
        campos_extra={
            "categoria_id": cat_id,
            "descuentos_forma_pago": descuentos_forma_pago(html),
        },
    )


def scrapear(limite_urls: int | None = None) -> Iterator[list[ProductoScrapeado]]:
    lote: list[ProductoScrapeado] = []
    with ClienteHTTP(LIMITE, timeout=90.0) as cli:
        medicamentos = ids_bajo_medicamentos(mapa_categorias(cli))

        resp = cli.get(SITEMAP_PRODUCTOS)
        if resp is None:
            raise RuntimeError("No se pudo leer el sitemap de productos de Catedral")
        urls = RE_LOC.findall(resp.text)
        if limite_urls:
            urls = urls[:limite_urls]

        for url in urls:
            pagina = cli.get(url)
            if pagina is None:
                continue
            p = parsear_ficha(url, pagina.text, medicamentos)
            if p is not None and p.sku_farmacia:
                lote.append(p)
            if len(lote) >= TAM_LOTE:
                yield lote
                lote = []
    if lote:
        yield lote


def main() -> None:
    ap = argparse.ArgumentParser(description="Scraper de Farmacia Catedral")
    ap.add_argument("--limite", type=int, help="solo N fichas")
    ap.add_argument("--sin-guardar", action="store_true", help="no escribe en Supabase")
    args = ap.parse_args()

    if args.sin_guardar:
        for lote in scrapear(args.limite):
            for p in lote[:10]:
                print(f"{p.condicion_venta:15} {p.precio_oferta!s:>10} ean={p.ean!s:<14} "
                      f"{(p.categoria_ruta or '-')[:22]:24} {p.nombre[:40]}")
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

    print(f"[catedral] {total | {'bajas': bajas}}")


if __name__ == "__main__":
    main()
