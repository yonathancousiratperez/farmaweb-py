"""Scraper de Farmatotal (WooCommerce + tema Bacola).

Decision de diseno: se recorre por LISTADOS de categoria, no por fichas.

La Store API (`/wp-json/wc/store/products`) esta deshabilitada — todo `/wp-json/`
devuelve 404 — asi que no hay JSON oficial. Pero el listado del tema acepta
`?perpage=N` sin tope, y cada tarjeta ya trae nombre, URL, imagen, precio normal,
precio web, % de descuento y stock. Con `perpage=300` el catalogo entero sale en
decenas de peticiones en vez de las ~40.000 que costaria ficha por ficha.

Lo unico que la tarjeta NO trae es el EAN. Vive solo en la ficha (JSON-LD `sku`,
que en Farmatotal es el codigo de barras real de 13 digitos). Como el EAN no
cambia y el precio si, se separan en dos modos: el scrape diario recorre listados,
y `--enriquecer-ean` completa fichas de a tandas para los productos que aun no lo
tienen. T6 (matching) depende de ese campo, no el precio.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterator

from selectolax.parser import HTMLParser

from .base import ClienteHTTP, Limite
from .db import ProductoScrapeado, conectar, guardar, marcar_bajas

SLUG = "farmatotal"
BASE = "https://www.farmatotal.com.py"

# Categorias raiz del menu. "ofertas" queda afuera a proposito: no es una rama de
# la taxonomia sino una vista promocional armada con productos que ya vienen de
# las otras ocho, y pisaria su categoria_ruta real.
CATEGORIAS = [
    "bazar-y-hogar",
    "belleza",
    "fragancias",
    "higiene-personal",
    "infantiles",
    "mamas-y-bebes",
    "medicamentos",
    "nutricion-y-deporte",
]

# Una pagina de 300 tarjetas tarda ~10 s en generarse del lado del servidor, asi
# que 1 req/s ya deja al sitio con margen de sobra.
LIMITE = Limite(req_por_seg=1.0, concurrencia=1)
PERPAGE = 300
TAM_LOTE = 500

# Tope de seguridad por categoria: si el sitio dejara de devolver 404 al pasarse
# de la ultima pagina, el while de abajo no tendria como terminar.
MAX_PAGINAS = 200

RE_POST_ID = re.compile(r"\bpost-(\d+)\b")
RE_CAT_CLASE = re.compile(r"\bproduct_cat-([a-z0-9\-]+)\b")
RE_LD_JSON = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
RE_EAN = re.compile(r"^\d{8,14}$")


def _guaranies(texto: str) -> float | None:
    """'Precio Web: G 14.600' -> 14600.0. En guaranies el punto es de miles."""
    digitos = re.sub(r"[^\d]", "", texto)
    return float(digitos) if digitos else None


def clasificar_condicion(categoria_raiz: str) -> str:
    """Falla cerrado: en Farmatotal la ficha no declara si requiere receta.

    Sin ese dato, todo lo que cuelga de 'medicamentos' se trata como bajo receta
    y por lo tanto sale sin precio. Es la unica opcion segura frente a la Ley
    1119/97 Art. 25; T5 (listado DINAVISA) va a liberar los de venta libre.
    """
    return "bajo_receta" if categoria_raiz == "medicamentos" else "no_medicamento"


def parsear_tarjeta(nodo, categoria_raiz: str) -> ProductoScrapeado | None:
    clases = nodo.attributes.get("class", "")
    m = RE_POST_ID.search(clases)
    enlace = nodo.css_first("h3.product-title a")
    if not m or enlace is None:
        return None

    # El id de post de WordPress es el unico identificador estable: el slug de la
    # URL cambia si le corrigen el nombre al producto.
    sku = m.group(1)
    nombre = (enlace.attributes.get("title") or enlace.text()).strip()
    url = enlace.attributes.get("href") or ""

    # <del> = "Precio Normal", <ins> = "Precio Web". Sin oferta, el tema imprime
    # un solo precio sin del/ins.
    precio_bloque = nodo.css_first("span.price")
    lista = oferta = None
    if precio_bloque is not None:
        nodo_del = precio_bloque.css_first("del")
        nodo_ins = precio_bloque.css_first("ins")
        if nodo_del is not None and nodo_ins is not None:
            lista = _guaranies(nodo_del.text())
            oferta = _guaranies(nodo_ins.text())
        else:
            oferta = _guaranies(precio_bloque.text())
    if lista is not None and oferta is not None and lista <= oferta:
        lista = None

    pct = None
    badge = nodo.css_first("span.porc_dcto")
    if badge is not None and (d := re.search(r"(\d+)", badge.text())):
        pct = float(d.group(1))
    elif lista and oferta:
        pct = round((lista - oferta) / lista * 100, 2)

    imagen = nodo.css_first(".thumbnail-wrapper img")
    # Las clases product_cat- mezclan la subcategoria real con la raiz y con
    # "ofertas", que es una vista promocional. Sin filtrarlas, la ruta de un
    # producto en promo quedaria "bazar-y-hogar > ofertas".
    subcats = [c for c in RE_CAT_CLASE.findall(clases)
               if c not in CATEGORIAS and c != "ofertas"]
    disponible = nodo.css_first(".product-available")

    return ProductoScrapeado(
        sku_farmacia=sku,
        nombre=nombre,
        url_producto=url,
        condicion_venta=clasificar_condicion(categoria_raiz),
        imagen_url=(imagen.attributes.get("src") if imagen is not None else None),
        categoria_ruta=" > ".join([categoria_raiz] + subcats[:1]),
        precio_lista=lista,
        precio_oferta=oferta,
        descuento_pct=pct,
        campos_extra={
            "subcategorias": subcats,
            "stock_texto": disponible.text().strip() if disponible is not None else None,
        },
    )


def _url_pagina(categoria: str, pagina: int) -> str:
    sufijo = "" if pagina == 1 else f"page/{pagina}/"
    return f"{BASE}/categoria/{categoria}/{sufijo}?perpage={PERPAGE}"


def scrapear(limite_paginas: int | None = None) -> Iterator[list[ProductoScrapeado]]:
    """Genera lotes de productos recorriendo los listados de cada categoria.

    Avanza de pagina hasta que el sitio devuelve 404 (o una pagina sin tarjetas):
    el widget de paginacion no publica el numero de la ultima pagina cuando
    perpage es grande, asi que no hay un total en que confiar.

    Generador como en farmacenter: quien llama escribe cada lote apenas lo
    recibe, en vez de acumular decenas de miles de objetos y jugarse todo a una
    escritura final.
    """
    lote: list[ProductoScrapeado] = []
    vistos: set[str] = set()
    paginas_hechas = 0

    with ClienteHTTP(LIMITE, timeout=180.0) as cli:
        for categoria in CATEGORIAS:
            for pagina in range(1, MAX_PAGINAS + 1):
                if limite_paginas and paginas_hechas >= limite_paginas:
                    break
                resp = cli.get(_url_pagina(categoria, pagina))
                paginas_hechas += 1
                if resp is None:  # 404: nos pasamos de la ultima pagina
                    break
                tarjetas = HTMLParser(resp.text).css("div.product.type-product")
                if not tarjetas:
                    break
                for nodo in tarjetas:
                    p = parsear_tarjeta(nodo, categoria)
                    # Un producto puede figurar en dos categorias; gana la
                    # primera para no reescribir su ruta en cada pasada.
                    if p is not None and p.sku_farmacia not in vistos:
                        vistos.add(p.sku_farmacia)
                        lote.append(p)
                if len(lote) >= TAM_LOTE:
                    yield lote
                    lote = []
            if limite_paginas and paginas_hechas >= limite_paginas:
                break

    if lote:
        yield lote


def ean_desde_ficha(html: str) -> str | None:
    """El EAN vive en el JSON-LD del Product, campo `sku`.

    Se valida que sea numerico de 8-14 digitos: algunos productos llevan ahi un
    codigo interno alfanumerico, y meterlo como EAN romperia el matching de T6
    emparejando productos distintos.
    """
    for bloque in RE_LD_JSON.findall(html):
        try:
            datos = json.loads(bloque)
        except json.JSONDecodeError:
            continue
        for nodo in datos.get("@graph", [datos]) if isinstance(datos, dict) else []:
            if isinstance(nodo, dict) and nodo.get("@type") == "Product":
                sku = str(nodo.get("sku") or "").strip()
                if RE_EAN.match(sku):
                    return sku
    return None


SQL_SIN_EAN = """
select p.sku_farmacia, p.url_producto
from   productos p
join   farmacias f on f.id = p.farmacia_id
where  f.slug = %(slug)s and p.activo and p.ean is null
order  by p.id
limit  %(limite)s;
"""

SQL_SET_EAN = """
update productos set ean = %(ean)s
where  farmacia_id = (select id from farmacias where slug = %(slug)s)
  and  sku_farmacia = %(sku)s;
"""


def enriquecer_ean(limite: int) -> dict:
    """Completa el EAN de hasta `limite` productos visitando sus fichas.

    Corre aparte del scrape de precios y de a tandas: son miles de fichas, el
    dato no caduca, y no vale la pena pagarlas todos los dias.
    """
    hechos = fallidos = 0
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(SQL_SIN_EAN, {"slug": SLUG, "limite": limite})
            pendientes = cur.fetchall()

        with ClienteHTTP(LIMITE) as cli:
            for sku, url in pendientes:
                resp = cli.get(url)
                ean = ean_desde_ficha(resp.text) if resp is not None else None
                if ean is None:
                    fallidos += 1
                    continue
                with conn.cursor() as cur:
                    cur.execute(SQL_SET_EAN, {"ean": ean, "slug": SLUG, "sku": sku})
                hechos += 1
        conn.commit()
    return {"con_ean": hechos, "sin_ean": fallidos, "mirados": len(pendientes)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Scraper de Farmatotal")
    ap.add_argument("--limite", type=int, help="solo N paginas de listado")
    ap.add_argument("--sin-guardar", action="store_true", help="no escribe en Supabase")
    ap.add_argument("--enriquecer-ean", type=int, metavar="N",
                    help="en vez de scrapear precios, completa el EAN de N fichas")
    args = ap.parse_args()

    if args.enriquecer_ean:
        print(f"[farmatotal] {enriquecer_ean(args.enriquecer_ean)}")
        return

    if args.sin_guardar:
        for lote in scrapear(args.limite):
            for p in lote[:10]:
                ruta = (p.categoria_ruta or "")[:28]
                print(f"{p.condicion_venta:15} {p.precio_oferta!s:>10}  {ruta:30} {p.nombre[:45]}")
            print(f"-- lote de {len(lote)} --")
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
        bajas = 0 if args.limite else marcar_bajas(conn, SLUG, vistos)

    print(f"[farmatotal] {total | {'bajas': bajas}}")


if __name__ == "__main__":
    main()
