-- Farmaweb.py — T7: carga curada inicial de bancos y promociones bancarias.
--
-- FUENTE: la home de Farmacenter enlaza las bases y condiciones de ocho bancos.
-- Es la misma fuente que va a usar el bot detector de T13, y es mejor que las
-- webs de los bancos: las promos concretas (que comercio, que dias, que tope)
-- casi siempre viven dentro de la app del banco, no en su sitio publico.
--
-- Solo se cargan promociones cuyas bases y condiciones se pudieron LEER en el
-- PDF oficial. De los ocho bancos, tres publican PDF directo; de esos, dos
-- traen terminos verificables. Los demas quedan como banco sin promo: preferimos
-- una promo de menos que un tope inventado, que bajo la Ley 1334/98 seria
-- informacion enganosa sobre precios.
--
-- Idempotente: se puede reaplicar sin duplicar.

insert into bancos (nombre, slug) values
  ('Banco Nacional de Fomento', 'bnf'),
  ('Banco Basa',                'basa'),
  ('Zeta Banco',                'zeta'),
  ('ueno bank',                 'ueno'),
  ('Banco GNB',                 'gnb'),
  ('Banco Familiar',            'familiar'),
  ('Banco Continental',         'continental'),
  ('Financiera Paraguayo Japonesa', 'fpj')
on conflict (slug) do update set nombre = excluded.nombre;


-- ------------------------------------------------------------------ BNF
-- Bases: "Hasta 30% de Descuento + 10% de Reintegro en Farmacias".
-- Vigencia textual del PDF: "Todos los lunes. Del 02 al 30 de junio de 2025."
--
-- Esta promo YA VENCIO. Se carga igual, con sus fechas reales y estado
-- 'publicada', a proposito: es la prueba viva de que el auto-ocultado por fecha
-- funciona. Si aparece en el sitio, hay un bug en v_promos_vigentes.
--
-- tope_gs es el tope del REINTEGRO (Gs. 100.000), no el tope de compra
-- (Gs. 1.000.000). Confundirlos multiplicaria por diez el beneficio mostrado.
insert into promos_bancarias
  (banco_id, titulo, tipo, porcentaje, tope_gs, tarjetas, dias_semana,
   vigente_desde, vigente_hasta, url_bases, farmacias_aplicables, estado, fuente_url)
select b.id,
       'Hasta 30% de descuento + 10% de reintegro en farmacias',
       'reintegro',
       10,
       100000,
       array['Visa Clasica','Visa Oro','Visa Platinum'],
       array[1]::smallint[],                 -- lunes (ISO: 1 = lunes)
       date '2025-06-02',
       date '2025-06-30',
       'https://www.bnf.gov.py/uploads/Promocion_Reintegro_Farmacias_2025_b1ef6ef0bb.pdf',
       (select coalesce(array_agg(f.id), '{}')
        from farmacias f where f.slug in ('farmacenter','catedral','farmaoliva')),
       'publicada',
       'https://www.farmacenter.com.py/'
from   bancos b where b.slug = 'bnf'
  and  not exists (select 1 from promos_bancarias p
                   where p.banco_id = b.id and p.vigente_desde = date '2025-06-02');


-- ----------------------------------------------------------------- BASA
-- Bases: "Promocion - Farmacenter". Todos los martes, 10% de reintegro en el
-- extracto (ademas de 25%/20% de descuento en caja, que ya viene incluido en el
-- precio publicado por la farmacia y por eso no se modela aparte).
--
-- tope_gs = 200.000: el PDF fija "tope de compra por mes para reintegro
-- Gs. 2.000.000" y el reintegro es del 10%, o sea 200.000 como maximo devuelto.
-- El esquema guarda el tope del beneficio, no el de la compra.
--
-- 🟡 estado='pendiente': el PDF NO declara fecha de fin para la promo general de
-- los martes. `vigente_hasta` es una SUPOSICION (fin del ultimo dia especial
-- listado para 2026). Necesita confirmacion humana antes de publicarse — esa es
-- exactamente la regla del proyecto.
insert into promos_bancarias
  (banco_id, titulo, tipo, porcentaje, tope_gs, tarjetas, dias_semana,
   vigente_desde, vigente_hasta, url_bases, farmacias_aplicables, estado, fuente_url)
select b.id,
       'Martes de Farmacenter: 10% de reintegro',
       'reintegro',
       10,
       200000,
       array['Afinidad Farmacenter','Mastercard Black','Visa Signature'],
       array[2]::smallint[],                 -- martes
       date '2026-04-14',
       date '2026-12-22',
       'https://www.bancobasa.com.py/promociones-personas',
       (select coalesce(array_agg(f.id), '{}') from farmacias f where f.slug = 'farmacenter'),
       'pendiente',
       'https://www.farmacenter.com.py/'
from   bancos b where b.slug = 'basa'
  and  not exists (select 1 from promos_bancarias p
                   where p.banco_id = b.id and p.titulo like 'Martes de Farmacenter%');
