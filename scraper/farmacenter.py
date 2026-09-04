"""Scraper de Farmacenter (plataforma Fenicio eCommerce).

Es la farmacia mas simple de las cinco y por eso valida el pipeline entero:
robots.txt permisivo (Disallow vacio), sitemap con las ~10k fichas, y cada
ficha trae un blob JSON (#_jsonDataFicha_) con codigo, nombre, categoria,
marca, presentacion, stock, precio y — lo mas valioso — la caracteristica
"receta", que es la fuente directa de condicion_venta.

Uso:
    python -m scraper.farmacenter              # scrape completo -> Supabase
    python -m scraper.farmacenter --limite 20  # muestra, sin escribir
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import sys
from decimal import Decimal

from selectolax.parser import HTMLParser

from .base import ClienteHTTP, Limite
from .db import ProductoScrapeado, conectar, guardar, marcar_bajas

SLUG = "farmacenter"
BASE = "https://www.farmacenter.com.py"
SITEMAP_ARTICULOS = f"{BASE}/sitemap/catalogo-articulos.xml"

# robots.txt de Farmacenter no declara Crawl-delay. 2 req/s repartidos entre 2
# hilos es ~1.4 h para el catalogo completo: lento a proposito.
LIMITE = Limite(req_por_seg=2.0, concurrencia=2)

# Cada cuantas fichas se vuelca lo scrapeado. La corrida completa son ~80
# minutos: escribir una sola vez al final significa que un corte a los 79 tira
# todo. Con lotes se pierde, como mucho, el ultimo lote.
TAM_LOTE = 500

RE_JSON_FICHA = re.compile(r'id="_jsonDataFicha_">\s*(\{.*?\})\s*</div>', re.S)
RE_LOC = re.compile(r"<loc>(.*?)</loc>")

# Etiquetas de la faceta "receta" del sitio -> nuestro vocabulario.
MAPA_RECETA = {
    "venta libre": "libre",
    "venta bajo receta original archivada": "controlado",
    "venta bajo receta": "bajo_receta",
    "venta bajo receta simple": "bajo_receta",
}


def clasificar_condicion(receta: str | None, categoria: str | None) -> str:
    """Traduce la caracteristica del sitio a condicion_venta.

    Falla cerrado: si el producto esta bajo "Medicamentos" y el sitio no dice
    nada sobre la receta, se asume bajo_receta. Mostrar de mas el precio de un
    medicamento Rx viola la Ley 1119/97; ocultar de mas solo pierde una ficha,
    y T5 (listado DINAVISA) va a recuperar esos casos.
    """
    if receta:
        etiqueta = receta.strip().lower()
        if etiqueta in MAPA_RECETA:
            return MAPA_RECETA[etiqueta]
        if "controlad" in etiqueta or "psicotr" in etiqueta:
            return "controlado"
        if "receta" in etiqueta:
            return "bajo_receta"
        if "libre" in etiqueta:
            return "libre"
        return "bajo_receta"  # etiqueta nueva y desconocida: fallar cerrado
    if categoria and categoria.strip().lower().startswith("medicamento"):
        return "bajo_receta"
    return "no_medicamento"


def _monto(texto: str) -> Decimal | None:
    """'254.363' -> 254363. El punto es separador de miles en guaranies."""
    digitos = re.sub(r"[^\d]", "", texto)
    return Decimal(digitos) if digitos else None


def precios_desde_html(html: HTMLParser) -> tuple[Decimal | None, Decimal | None]:
    """Devuelve (precio_lista, precio_oferta) del bloque de precios de la ficha.

    La ficha trae ademas carruseles de productos relacionados, cada uno con su
    propio div.precios: hay que anclarse a #fichaProducto .preciosWrapper y
    quedarse con el primero, o se termina guardando el precio del producto de
    al lado.

    Fenicio tacha el precio de lista con <del class="precio lista"> y marca el
    vigente ("Cliente Fiel") con <strong class="precio venta">.
    """
    bloque = html.css_first("#fichaProducto .preciosWrapper .precios")
    if bloque is None:
        return None, None
    lista = oferta = None
    for nodo in bloque.css(".precio"):
        clases = set((nodo.attributes.get("class") or "").split())
        monto_nodo = nodo.css_first(".monto")
        if monto_nodo is None:
            continue
        valor = _monto(monto_nodo.text())
        if valor is None:
            continue
        if clases & {"lista", "anterior", "antes", "tachado", "normal"}:
            lista = valor
        elif clases & {"venta", "oferta"}:
            oferta = valor
    return lista, oferta


def parsear_ficha(url: str, html_texto: str) -> ProductoScrapeado | None:
    m = RE_JSON_FICHA.search(html_texto)
    if not m:
        return None
    d = json.loads(m.group(1))
    prod = d.get("producto", {})
    codigo = prod.get("codigo") or d.get("sku", {}).get("com")
    if not codigo:
        return None

    # PHP serializa los diccionarios vacios como [], no como {}.
    carac = d.get("carac") or {}
    if not isinstance(carac, dict):
        carac = {}

    html = HTMLParser(html_texto)
    lista, oferta = precios_desde_html(html)
    if oferta is None and d.get("precioMonto"):
        oferta = Decimal(str(d["precioMonto"]))
    if lista is not None and oferta is not None and lista <= oferta:
        lista = None  # tachado igual o menor: no es un descuento real

    descuento = None
    if lista and oferta:
        descuento = ((lista - oferta) / lista * 100).quantize(Decimal("0.01"))

    categoria = prod.get("categoria")
    return ProductoScrapeado(
        sku_farmacia=str(codigo),
        nombre=(prod.get("nombre") or d.get("nombre") or "").strip(),
        url_producto=(d.get("variante") or {}).get("url") or url,
        condicion_venta=clasificar_condicion(carac.get("receta"), categoria),
        marca=(prod.get("marca") or "").strip() or None,
        presentacion=d.get("nomPresentacion") or None,
        imagen_url=_absoluta((d.get("variante") or {}).get("img", {}).get("u")),
        categoria_ruta=categoria,
        precio_lista=lista,
        precio_oferta=oferta,
        descuento_pct=descuento,
    )


def _absoluta(u: str | None) -> str | None:
    if not u:
        return None
    return f"https:{u}" if u.startswith("//") else u


def urls_de_productos(cliente: ClienteHTTP) -> list[str]:
    r = cliente.get(SITEMAP_ARTICULOS)
    if r is None:
        raise RuntimeError("No se pudo leer el sitemap de articulos de Farmacenter")
    return [u.strip() for u in RE_LOC.findall(r.text)]


def scrapear(limite_urls: int | None = None):
    """Recorre el catalogo y va entregando lotes de productos ya parseados.

    Generador a proposito: quien llama escribe cada lote apenas lo recibe, en
    vez de acumular 10k objetos en memoria y jugarse todo a una escritura final.
    """
    with ClienteHTTP(LIMITE) as cliente:
        urls = urls_de_productos(cliente)
        if limite_urls:
            urls = urls[:limite_urls]
        print(f"[farmacenter] {len(urls)} fichas a recorrer", file=sys.stderr)

        lote: list[ProductoScrapeado] = []
        fallos = 0

        def trabajar(url: str) -> ProductoScrapeado | None:
            r = cliente.get(url)
            return parsear_ficha(url, r.text) if r is not None else None

        with concurrent.futures.ThreadPoolExecutor(LIMITE.concurrencia) as pool:
            for i, p in enumerate(pool.map(trabajar, urls), 1):
                if p is None:
                    fallos += 1
                else:
                    lote.append(p)
                if len(lote) >= TAM_LOTE:
                    yield lote
                    print(f"[farmacenter] {i}/{len(urls)} guardado", file=sys.stderr)
                    lote = []
        if lote:
            yield lote
    print(f"[farmacenter] recorrido terminado, {fallos} fichas sin datos", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description="Scraper de Farmacenter")
    ap.add_argument("--limite", type=int, help="solo N fichas")
    ap.add_argument("--sin-guardar", action="store_true", help="no escribe en Supabase")
    args = ap.parse_args()

    if args.sin_guardar:
        for lote in scrapear(args.limite):
            for p in lote[:10]:
                print(f"{p.condicion_venta:15} {p.precio_oferta!s:>10}  {p.nombre[:55]}")
        print("(no se escribio en la base)")
        return

    total = {"productos": 0, "precios": 0}
    vistos: list[str] = []
    with conectar() as conn:
        for lote in scrapear(args.limite):
            # parcial=True siempre: ningun lote conoce el catalogo completo, asi
            # que ninguno puede decidir bajas.
            r = guardar(conn, SLUG, lote, parcial=True)
            total["productos"] += r["productos"]
            total["precios"] += r["precios"]
            vistos.extend(p.sku_farmacia for p in lote)

        # Las bajas solo se aplican si se recorrio el catalogo entero. En una
        # corrida recortada, "ausente" significa "no lo mire".
        bajas = 0 if args.limite else marcar_bajas(conn, SLUG, vistos)

    print(f"[farmacenter] {total | {'bajas': bajas}}")


if __name__ == "__main__":
    main()
