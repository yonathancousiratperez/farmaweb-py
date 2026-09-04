-- T5 — condicion de venta segun DINAVISA.
--
-- Los cinco scrapers fallan cerrado: sin dato del sitio, todo lo que cuelga de
-- "Medicamentos" sale como bajo_receta y por lo tanto sin precio. Eso oculta de
-- mas (alcohol en gel, caramelos, jarabes de venta libre). El listado de
-- registros sanitarios de DINAVISA es la fuente oficial que permite corregirlo.
--
-- Se guarda en una columna aparte, no pisando `condicion_venta`, por una razon
-- concreta: el upsert del scraper reescribe `condicion_venta` en cada corrida.
-- Sin esta separacion, el trabajo del clasificador se perderia todas las noches
-- y el sitio volveria a ocultar los mismos productos.
alter table productos
  add column if not exists condicion_venta_dinavisa text
    check (condicion_venta_dinavisa in ('libre','bajo_receta','controlado')),
  -- El numero de registro sanitario deja auditable de donde salio cada
  -- clasificacion: sin el, "por que este producto muestra precio" no tiene
  -- respuesta verificable, y en un tema regulado eso hace falta.
  add column if not exists dinavisa_nro_rs text;

create index if not exists productos_dinavisa_idx
  on productos(condicion_venta_dinavisa)
  where condicion_venta_dinavisa is not null;

-- La vista publica NO expone estas columnas: el gate sigue leyendo
-- `condicion_venta`, que es el valor efectivo. Esto es solo la procedencia.
