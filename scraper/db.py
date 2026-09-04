"""Escritura a Supabase para los scrapers.

Se conecta por Postgres directo (pooler en modo sesion) en vez de PostgREST:
el scrape es un upsert masivo de ~10k filas por farmacia, y eso en REST son
10k round-trips. El rol es el owner, asi que hace bypass de RLS igual que la
secret key haria.

La contrasena sale de .env (FARMAWEB_SUPABASE_DB_PASSWORD) o de la variable de
entorno del mismo nombre, para que en GitHub Actions venga de un Secret.
"""

from __future__ import annotations

import os
import pathlib
import re
import unicodedata
from dataclasses import dataclass, field

import psycopg

RAIZ = pathlib.Path(__file__).resolve().parent.parent
REF_PROYECTO = "wdbezekfcmntcoagmlzm"
HOST_POOLER = "aws-0-sa-east-1.pooler.supabase.com"


@dataclass
class ProductoScrapeado:
    """Una fila cruda tal como la devuelve el sitio de una farmacia."""

    sku_farmacia: str
    nombre: str
    url_producto: str
    condicion_venta: str
    ean: str | None = None
    marca: str | None = None
    presentacion: str | None = None
    imagen_url: str | None = None
    categoria_ruta: str | None = None
    precio_lista: float | None = None
    precio_oferta: float | None = None
    descuento_pct: float | None = None
    campos_extra: dict = field(default_factory=dict)


def slugificar(texto: str) -> str:
    base = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", base.lower())).strip("-")


def _password() -> str:
    if valor := os.environ.get("FARMAWEB_SUPABASE_DB_PASSWORD"):
        return valor
    env = RAIZ / ".env"
    if env.exists():
        for linea in env.read_text(encoding="utf-8").splitlines():
            if linea.startswith("FARMAWEB_SUPABASE_DB_PASSWORD="):
                return linea.split("=", 1)[1].strip()
    raise RuntimeError("Falta FARMAWEB_SUPABASE_DB_PASSWORD (.env o entorno)")


def conectar() -> psycopg.Connection:
    dsn = (
        f"postgresql://postgres.{REF_PROYECTO}:{_password()}"
        f"@{HOST_POOLER}:5432/postgres?sslmode=require"
    )
    return psycopg.connect(dsn)


def id_farmacia(conn: psycopg.Connection, slug: str) -> int:
    with conn.cursor() as cur:
        cur.execute("select id from farmacias where slug = %s", (slug,))
        fila = cur.fetchone()
    if fila is None:
        raise RuntimeError(f"Farmacia '{slug}' no cargada (ver db/migrations/002)")
    return fila[0]


SQL_STAGING = """
create temp table stg_productos (
  sku_farmacia    text,
  ean             text,
  nombre          text,
  marca           text,
  presentacion    text,
  url_producto    text,
  imagen_url      text,
  condicion_venta text,
  categoria_ruta  text,
  precio_lista    numeric(12,2),
  precio_oferta   numeric(12,2),
  descuento_pct   numeric(5,2)
) on commit drop;
"""

# Categorias: por ahora una fila por ruta completa de la farmacia. Unificar el
# arbol entre las 5 farmacias es T6, no esto.
SQL_CATEGORIAS = """
insert into categorias (slug, nombre)
select distinct on (slug) slug, nombre from (
  select %s || '-' || regexp_replace(lower(translate(s.categoria_ruta,
             'áéíóúüñÁÉÍÓÚÜÑ', 'aeiouunAEIOUUN')), '[^a-z0-9]+', '-', 'g') as slug,
         trim(split_part(s.categoria_ruta, '>', array_length(
             string_to_array(s.categoria_ruta, '>'), 1))) as nombre
  from stg_productos s where s.categoria_ruta is not null
) t
on conflict (slug) do nothing;
"""

SQL_UPSERT_PRODUCTOS = """
insert into productos (farmacia_id, sku_farmacia, ean, nombre, marca, presentacion,
                       categoria_id, url_producto, imagen_url, condicion_venta,
                       activo, visto_ultima_vez)
select %(fid)s, s.sku_farmacia, s.ean, s.nombre, s.marca, s.presentacion,
       c.id, s.url_producto, s.imagen_url, s.condicion_venta, true, now()
from   stg_productos s
left   join categorias c on c.slug = %(pref)s || '-' || regexp_replace(
         lower(translate(s.categoria_ruta, 'áéíóúüñÁÉÍÓÚÜÑ', 'aeiouunAEIOUUN')),
         '[^a-z0-9]+', '-', 'g')
on conflict (farmacia_id, sku_farmacia) do update set
  ean = excluded.ean, nombre = excluded.nombre, marca = excluded.marca,
  presentacion = excluded.presentacion, categoria_id = excluded.categoria_id,
  url_producto = excluded.url_producto, imagen_url = excluded.imagen_url,
  condicion_venta = excluded.condicion_venta,
  activo = true, visto_ultima_vez = now();
"""

# Solo se inserta precio si cambio respecto del ultimo capturado. Un scrape
# diario sobre 10k productos que no cambian de precio llenaria la tabla de
# filas identicas y el free tier tiene 500 MB.
SQL_INSERT_PRECIOS = """
insert into precios (producto_id, precio_lista, precio_oferta, descuento_pct)
select p.id, s.precio_lista, s.precio_oferta, s.descuento_pct
from   stg_productos s
join   productos p on p.farmacia_id = %(fid)s and p.sku_farmacia = s.sku_farmacia
left   join lateral (
         select pr.precio_lista, pr.precio_oferta, pr.descuento_pct
         from   precios pr where pr.producto_id = p.id
         order  by pr.capturado_en desc limit 1
       ) ult on true
where  s.precio_oferta is not null
  and  (ult.precio_oferta is null
        or ult.precio_oferta  is distinct from s.precio_oferta
        or ult.precio_lista   is distinct from s.precio_lista
        or ult.descuento_pct  is distinct from s.descuento_pct);
"""

# Lo que dejo de aparecer en el catalogo se marca inactivo, no se borra: el
# historial de precios sigue teniendo sentido y las FK no se rompen.
SQL_BAJAS = """
update productos p set activo = false
where  p.farmacia_id = %(fid)s and p.activo
  and  not exists (select 1 from stg_productos s where s.sku_farmacia = p.sku_farmacia);
"""


def guardar(conn: psycopg.Connection, farmacia_slug: str,
            productos: list[ProductoScrapeado], *, parcial: bool = False) -> dict[str, int]:
    """Vuelca el scrape de una farmacia en una sola transaccion.

    Con parcial=True se omite la baja de los ausentes: en un scrape recortado
    (prueba, o corrida que fallo a la mitad) "ausente" no significa "ya no
    esta", significa "no lo mire".
    """
    fid = id_farmacia(conn, farmacia_slug)
    with conn.cursor() as cur:
        cur.execute(SQL_STAGING)
        with cur.copy(
            "copy stg_productos (sku_farmacia, ean, nombre, marca, presentacion,"
            " url_producto, imagen_url, condicion_venta, categoria_ruta,"
            " precio_lista, precio_oferta, descuento_pct) from stdin"
        ) as copy:
            for p in productos:
                copy.write_row((p.sku_farmacia, p.ean, p.nombre, p.marca,
                                p.presentacion, p.url_producto, p.imagen_url,
                                p.condicion_venta, p.categoria_ruta,
                                p.precio_lista, p.precio_oferta, p.descuento_pct))
        cur.execute(SQL_CATEGORIAS, (farmacia_slug,))
        cur.execute(SQL_UPSERT_PRODUCTOS, {"fid": fid, "pref": farmacia_slug})
        productos_tocados = cur.rowcount
        cur.execute(SQL_INSERT_PRECIOS, {"fid": fid})
        precios_nuevos = cur.rowcount
        bajas = 0
        if not parcial:
            cur.execute(SQL_BAJAS, {"fid": fid})
            bajas = cur.rowcount
    conn.commit()
    return {"productos": productos_tocados, "precios": precios_nuevos, "bajas": bajas}


SQL_BAJAS_POR_LISTA = """
update productos p set activo = false
where  p.farmacia_id = %(fid)s and p.activo
  and  not exists (select 1 from stg_skus s where s.sku_farmacia = p.sku_farmacia);
"""


def marcar_bajas(conn: psycopg.Connection, farmacia_slug: str,
                 skus_vistos: list[str]) -> int:
    """Desactiva los productos de la farmacia que no aparecieron en el scrape.

    Va separado de guardar() porque con escritura por lotes ningun lote conoce
    el catalogo completo: la baja solo tiene sentido cuando la corrida termino
    entera. Se desactiva, nunca se borra.
    """
    fid = id_farmacia(conn, farmacia_slug)
    with conn.cursor() as cur:
        cur.execute("create temp table stg_skus (sku_farmacia text) on commit drop;")
        with cur.copy("copy stg_skus (sku_farmacia) from stdin") as copy:
            for sku in skus_vistos:
                copy.write_row((sku,))
        cur.execute(SQL_BAJAS_POR_LISTA, {"fid": fid})
        bajas = cur.rowcount
    conn.commit()
    return bajas
