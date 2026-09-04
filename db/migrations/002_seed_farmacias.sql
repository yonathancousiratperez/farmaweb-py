-- Farmaweb.py — T2 (paso previo): carga de las 5 farmacias del MVP.
-- Idempotente: se puede reaplicar sin duplicar (on conflict sobre slug).
-- Baja de una farmacia = activa=false, nunca delete (hay FKs a productos).

insert into farmacias (nombre, slug, url_base) values
  ('Farmacenter',       'farmacenter', 'https://www.farmacenter.com.py'),
  ('Farmatotal',        'farmatotal',  'https://www.farmatotal.com.py'),
  ('Farmaoliva',        'farmaoliva',  'https://www.farmaoliva.com.py'),
  ('Punto Farma',       'puntofarma',  'https://www.puntofarma.com.py'),
  ('Farmacia Catedral', 'catedral',    'https://www.farmaciacatedral.com.py')
on conflict (slug) do update
  set nombre   = excluded.nombre,
      url_base = excluded.url_base;
