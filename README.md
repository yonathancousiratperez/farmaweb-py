# Farmaweb.py

Buscador y comparador de precios de farmacias del Paraguay. Muestra el precio
final real cruzando el descuento de la farmacia con el reintegro bancario
vigente.

## Que hace

- Agrega el catalogo publico de las principales farmacias del pais con tienda online.
- Muestra precio de lista, precio con descuento y la fecha y hora de captura.
- Cruza las promociones bancarias vigentes y aplica el **tope** del reintegro,
  no solo el porcentaje.
- Enlaza siempre a la ficha original de la farmacia.

## Gate legal de medicamentos bajo receta

Los productos con `condicion_venta IN ('bajo_receta','controlado')` se muestran
**sin precio, sin porcentaje de descuento, sin promocion bancaria y fuera de
cualquier ranking**. Solo nombre, presentacion, en que farmacias hay stock y el
enlace.

Es por la **Ley 1119/97, Art. 25 inc. 10**, que prohibe la publicidad de
medicamentos de venta bajo receta salvo los avisos de existencia en plaza.

> El filtro vive en la vista `v_productos_publicos` de Postgres, **no en React**.
> Un bug de interfaz no debe poder filtrar precios de Rx. Si se agrega un
> endpoint o una vista que exponga precios, verificar que respete el gate antes
> de mergear.

## Arquitectura

```
GitHub Actions (cron)         Supabase (free)          GitHub Pages
  scrape.yml         write→   Postgres + RLS   ←read   Astro estatico
  matrix 3 farmacias          vistas publicas  anon    + isla React
```

## Estructura

| Ruta | Que hay |
|---|---|
| `scraper/` | `base.py` (cliente HTTP con rate-limit), `db.py` (escritura), un modulo por farmacia |
| `db/migrations/` | Esquema, vistas, RPC de busqueda y seeds |
| `web/` | Sitio Astro + Tailwind + islas React |
| `.github/workflows/` | Scrape diario y deploy a Pages |

## Correr local

```bash
pip install -r scraper/requirements.txt
python -m scraper.farmacenter --limite 100 --sin-guardar   # sin escribir en la base
npm install --prefix web && npm run dev --prefix web
```

Las migraciones se aplican con:

```bash
python db/aplicar_migracion.py db/migrations/00X_lo_que_sea.sql
```

## Secrets que necesitan los workflows

| Secret | Para que | Donde |
|---|---|---|
| `FARMAWEB_SUPABASE_DB_PASSWORD` | Escritura del scraper contra el pooler de Supabase | `scrape.yml` |
| `PUBLIC_SUPABASE_URL` | Lecturas del sitio | `deploy.yml` |
| `PUBLIC_SUPABASE_ANON_KEY` | Lecturas del sitio (publica por diseno; su seguridad depende de RLS) | `deploy.yml` |

Nada de esto va en el codigo ni en archivos `.md`. Localmente viven en `.env`,
que esta en `.gitignore`.

## Scraping responsable

- User-agent identificable (`FarmawebPyBot`) con URL de contacto.
- Rate-limit por sitio; se respeta el `Crawl-delay` que declare cada `robots.txt`.
- **Nunca** se toca `/api/` de Farmacia Catedral (prohibido por su robots.txt).
- Solo paginas publicas de catalogo. No se tocan carrito, cuenta ni checkout.
- Baja de una farmacia = `activa = false`, nunca borrar codigo.

## Promociones bancarias

Ninguna se publica sin revision humana. El detector automatico solo inserta con
`estado = 'pendiente'`. Un tope mal leido cambia por completo la decision de
compra, y publicarlo mal seria informacion enganosa bajo la Ley 1334/98.

## Licencia

MIT para el codigo. Los datos de producto pertenecen a las farmacias de origen.
