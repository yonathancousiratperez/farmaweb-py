-- Farmaweb.py — arreglo: persistir `campos_extra`.
--
-- El dataclass ProductoScrapeado siempre tuvo `campos_extra`, pero no existia
-- la columna y guardar() nunca lo escribia: todos los scrapers lo venian
-- descartando en silencio. Se perdia, entre otras cosas:
--   · `descuentos_forma_pago` de Catedral — descuentos por medio de pago con
--     porcentaje, dia y vigencia. Es el insumo directo del detector de T13.
--   · las subcategorias de Farmatotal, que suelen ser el principio activo.
--   · el codigo interno de Farmaoliva.
--
-- jsonb y no json: se va a consultar por clave (`campos_extra->'...'`), y jsonb
-- es el unico de los dos que indexa.

alter table productos
  add column if not exists campos_extra jsonb not null default '{}'::jsonb;

-- Indice GIN para poder buscar productos por lo que haya adentro sin escanear
-- la tabla entera; lo va a necesitar T13 para encontrar los que traen promo.
create index if not exists productos_campos_extra_idx
  on productos using gin (campos_extra);

-- La vista publica NO expone campos_extra: es material crudo de scraping, con
-- datos de terceros sin revisar. Al navegador no le sirve y no deberia verlo.
