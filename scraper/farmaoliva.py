"""Scraper de Farmaoliva (plataforma Dattamax / "ecommercepro").

robots.txt es `Disallow:` vacio — todo permitido. El sitemap trae 21.854 fichas,
pero no hace falta visitarlas: la tarjeta del listado ya trae TODO, incluido el
EAN en `data-product_ean`. Es la unica de las tres farmacias HTTP que lo publica
en el listado, asi que aca no hay paso de enriquecimiento aparte.

El listado es de 24 productos fijos (no hay parametro de tamano de pagina) y cada
pagina pesa ~1,5 MB porque el menu completo y los badges de descuento van
embebidos en base64. Aun asi, 24 productos por pedido gana por lejos contra una
ficha por pedido.

Jerarquia: el menu (`ul.nav.yamm`) es un arbol anidado de tres niveles. Se parsea
para dos cosas: armar `categoria_ruta` completa, y saber si una categoria cuelga
de "Medicamentos" — el unico dato con el que se puede clasificar `condicion_venta`
en este sitio.
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Iterator
from dataclasses import dataclass

from selectolax.parser import HTMLParser

from .base import ClienteHTTP, Limite
from .db import ProductoScrapeado, conectar, guardar, marcar_bajas

SLUG = "farmaoliva"
BASE = "https://www.farmaoliva.com.py"
RAIZ_MEDICAMENTOS = "medicamentos"

LIMITE = Limite(req_por_seg=1.5, concurrencia=2)
TAM_LOTE = 500
MAX_PAGINAS = 300

RE_CAT_URL = re.compile(r"catalogo/([a-z0-9\-]+)-c(\d+)$")
RE_PROD_URL = re.compile(r"-p(\d+)$")
RE_RESULTADOS = re.compile(r"de\s+([\d.]+)\s+resultados")


@dataclass(frozen=True)
class Categoria:
    id: str
    slug: str
    ruta: str          # "Medicamentos > Analgesicos > Migrana"
    raiz_slug: str     # slug de la categoria de primer nivel
    nivel: int

    @property
    def url(self) -> str:
        return f"{BASE}/catalogo/{self.slug}-c{self.id}"


def _guaranies(texto: str) -> float | None:
    digitos = re.sub(r"[^\d]", "", texto)
    return float(digitos) if digitos else None


def arbol_categorias(html: str) -> list[Categoria]:
    """Extrae el arbol de categorias del megamenu.

    Se recorre recursivamente el <ul> del menu en vez de juntar los enlaces
    sueltos: sin el anidamiento no hay forma de saber que "Hipertension" cuelga
    de "Medicamentos", y de ahi sale la clasificacion Rx.
    """
    menu = HTMLParser(html).css_first("ul.nav.yamm")
    if menu is None:
        raise RuntimeError("No se encontro el menu de categorias (ul.nav.yamm)")

    cats: list[Categoria] = []

    def recorrer(lista, ruta: list[str], raiz: str | None) -> None:
        for item in lista.iter():
            if item.tag != "li":
                continue
            enlace = item.css_first("a")
            if enlace is None:
                continue
            m = RE_CAT_URL.search(enlace.attributes.get("href") or "")
            if not m:
                continue
            slug, cid = m.group(1), m.group(2)
            nombre = (enlace.attributes.get("title") or enlace.text()).strip()
            ruta_hija = ruta + [nombre]
            raiz_hija = raiz or slug
            cats.append(Categoria(cid, slug, " > ".join(ruta_hija), raiz_hija, len(ruta_hija)))
            # Solo los <ul> hijos directos: css("ul") traeria tambien los nietos
            # y aplanaria el arbol un nivel de mas.
            for sub in item.iter():
                if sub.tag == "ul":
                    recorrer(sub, ruta_hija, raiz_hija)

    recorrer(menu, [], None)
    # Un mismo id puede aparecer dos veces en el menu; gana la primera aparicion.
    unicas: dict[str, Categoria] = {}
    for c in cats:
        unicas.setdefault(c.id, c)
    return list(unicas.values())


def parsear_tarjeta(nodo, cat: Categoria) -> ProductoScrapeado | None:
    boton = nodo.css_first("a.add_to_cart_button")
    enlace = nodo.css_first("a.ecommercepro-LoopProduct-link")
    if boton is None or enlace is None:
        return None
    attrs = boton.attributes
    pid = attrs.get("data-product_id")
    if not pid:
        return None

    href = enlace.attributes.get("href") or ""
    url = href if href.startswith("http") else f"{BASE}/{href.lstrip('/')}"

    bloque = nodo.css_first("span.price")
    lista = oferta = None
    if bloque is not None:
        ins, dele = bloque.css_first("ins"), bloque.css_first("del")
        # ins = precio vigente, del = precio tachado. Sin oferta solo hay <span>.
        oferta = _guaranies(ins.text()) if ins is not None else _guaranies(bloque.text())
        lista = _guaranies(dele.text()) if dele is not None else None
    if lista is not None and oferta is not None and lista <= oferta:
        lista = None
    if oferta is None and (p := attrs.get("data-product_price")):
        oferta = _guaranies(p)

    ean = (attrs.get("data-product_ean") or "").strip() or None
    if ean is not None and not ean.isdigit():
        ean = None

    titulo = nodo.css_first("h2.ecommercepro-loop-product__title")
    nombre = (titulo.text() if titulo is not None else attrs.get("data-product_name", "")).strip()

    imagen = nodo.css_first("img")
    return ProductoScrapeado(
        sku_farmacia=pid,
        nombre=nombre,
        url_producto=url,
        condicion_venta=clasificar_condicion(cat),
        ean=ean,
        marca=(attrs.get("data-product_brand") or "").strip() or None,
        imagen_url=(imagen.attributes.get("src") if imagen is not None else None),
        categoria_ruta=cat.ruta,
        precio_lista=lista,
        precio_oferta=oferta,
        descuento_pct=(round((lista - oferta) / lista * 100, 2) if lista and oferta else None),
        campos_extra={"codigo_interno": attrs.get("data-product_item"), "categoria_id": cat.id},
    )


def clasificar_condicion(cat: Categoria) -> str:
    """Falla cerrado: Farmaoliva no publica si el producto requiere receta.

    Todo lo que cuelgue de la rama "Medicamentos" se trata como bajo receta y
    sale sin precio (Ley 1119/97 Art. 25). T5 (listado DINAVISA) va a liberar
    despues los de venta libre.
    """
    return "bajo_receta" if cat.raiz_slug == RAIZ_MEDICAMENTOS else "no_medicamento"


def scrapear(limite_paginas: int | None = None) -> Iterator[list[ProductoScrapeado]]:
    """Genera lotes recorriendo cada categoria, de la mas profunda a la mas general.

    El orden importa: un producto aparece en su hoja y en todos sus ancestros.
    Recorriendo primero las hojas, el primer registro que se queda es el de la
    categoria mas especifica, que es la ruta util para el buscador.
    """
    lote: list[ProductoScrapeado] = []
    vistos: set[str] = set()
    paginas_hechas = 0

    with ClienteHTTP(LIMITE, timeout=120.0) as cli:
        inicio = cli.get(f"{BASE}/catalogo/{RAIZ_MEDICAMENTOS}-c3")
        if inicio is None:
            raise RuntimeError("No se pudo cargar el catalogo para leer el menu")
        cats = sorted(arbol_categorias(inicio.text), key=lambda c: -c.nivel)

        for cat in cats:
            for pagina in range(1, MAX_PAGINAS + 1):
                if limite_paginas and paginas_hechas >= limite_paginas:
                    break
                url = cat.url if pagina == 1 else f"{cat.url}.{pagina}"
                resp = cli.get(url)
                paginas_hechas += 1
                if resp is None:
                    break
                arbol = HTMLParser(resp.text)
                tarjetas = arbol.css("div.product")
                if not tarjetas:
                    break
                nuevos = 0
                for nodo in tarjetas:
                    p = parsear_tarjeta(nodo, cat)
                    if p is not None and p.sku_farmacia not in vistos:
                        vistos.add(p.sku_farmacia)
                        lote.append(p)
                        nuevos += 1
                if len(lote) >= TAM_LOTE:
                    yield lote
                    lote = []
                # El sitio repite la ultima pagina en vez de dar 404 cuando se
                # pide una pagina de mas; si no entro nada nuevo, se corta.
                if nuevos == 0 and pagina > 1:
                    break
            if limite_paginas and paginas_hechas >= limite_paginas:
                break

    if lote:
        yield lote


def main() -> None:
    ap = argparse.ArgumentParser(description="Scraper de Farmaoliva")
    ap.add_argument("--limite", type=int, help="solo N paginas de listado")
    ap.add_argument("--sin-guardar", action="store_true", help="no escribe en Supabase")
    args = ap.parse_args()

    if args.sin_guardar:
        for lote in scrapear(args.limite):
            for p in lote[:10]:
                print(f"{p.condicion_venta:15} {p.precio_oferta!s:>10} ean={p.ean!s:<14} "
                      f"{(p.categoria_ruta or '')[:34]:36} {p.nombre[:40]}")
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

    print(f"[farmaoliva] {total | {'bajas': bajas}}")


if __name__ == "__main__":
    main()
