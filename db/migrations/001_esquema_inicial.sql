-- Farmaweb.py — T1: esquema inicial
-- Proyecto Supabase: farmaweb-py (wdbezekfcmntcoagmlzm, sa-east-1)
--
-- Principio rector: la logica sensible vive en la base, no en el frontend.
-- La anon key viaja al navegador por diseno; si el gate legal de medicamentos
-- Rx estuviera en React, un bug de UI filtraria precios. Aca la API nunca los
-- devuelve.

create schema if not exists extensions;
create extension if not exists unaccent schema extensions;
create extension if not exists pg_trgm schema extensions;

-- unaccent() es STABLE (depende del diccionario), asi que Postgres la rechaza en
-- un indice. El wrapper fija el diccionario por nombre, lo que la vuelve
-- determinista y permite indexarla. Usar SIEMPRE f_unaccent en indices y en las
-- consultas de busqueda: si la consulta llama a unaccent() a secas, el indice no
-- se usa.
create or replace function f_unaccent(text) returns text
language sql immutable strict parallel safe as
$$ select extensions.unaccent('extensions.unaccent'::regdictionary, $1) $$;

-- ---------------------------------------------------------------- catalogo

create table farmacias (
  id         bigint generated always as identity primary key,
  nombre     text not null,
  slug       text not null unique,
  url_base   text not null,
  logo_url   text,
  activa     boolean not null default true,   -- baja de una farmacia = false, nunca delete
  creado_en  timestamptz not null default now()
);

create table categorias (
  id       bigint generated always as identity primary key,
  slug     text not null unique,
  nombre   text not null,
  padre_id bigint references categorias(id) on delete set null
);

create table productos (
  id              bigint generated always as identity primary key,
  farmacia_id     bigint not null references farmacias(id) on delete cascade,
  sku_farmacia    text   not null,
  ean             text,
  nombre          text   not null,
  nombre_norm     text,
  marca           text,
  categoria_id    bigint references categorias(id) on delete set null,
  presentacion    text,
  url_producto    text not null,   -- deep-link a la ficha original: mandamos trafico, no lo retenemos
  imagen_url      text,
  condicion_venta text not null default 'libre'
    check (condicion_venta in ('libre','bajo_receta','controlado','no_medicamento')),
  activo           boolean not null default true,
  visto_ultima_vez timestamptz not null default now(),
  unique (farmacia_id, sku_farmacia)
);

create index productos_ean_idx        on productos(ean) where ean is not null;
create index productos_categoria_idx  on productos(categoria_id);
create index productos_condicion_idx  on productos(condicion_venta);
create index productos_nombre_fts_idx on productos
  using gin (to_tsvector('spanish', f_unaccent(nombre)));
create index productos_nombre_trgm_idx on productos
  using gin (f_unaccent(nombre) extensions.gin_trgm_ops);

create table precios (
  id            bigint generated always as identity primary key,
  producto_id   bigint not null references productos(id) on delete cascade,
  precio_lista  numeric(12,2),
  precio_oferta numeric(12,2) not null,
  descuento_pct numeric(5,2),
  capturado_en  timestamptz not null default now()
);

create index precios_producto_fecha_idx on precios(producto_id, capturado_en desc);

-- ------------------------------------------------- agrupacion cross-farmacia

create table grupos (
  id               bigint generated always as identity primary key,
  ean              text unique,
  nombre_canonico  text not null,
  principio_activo text,
  concentracion    text,
  presentacion     text
);

create table grupo_items (
  grupo_id    bigint not null references grupos(id) on delete cascade,
  producto_id bigint not null references productos(id) on delete cascade,
  confianza   numeric(4,3) not null check (confianza between 0 and 1),
  primary key (grupo_id, producto_id)
);

-- ---------------------------------------------------------- promos bancarias

create table bancos (
  id       bigint generated always as identity primary key,
  nombre   text not null,
  slug     text not null unique,
  logo_url text
);

create table promos_bancarias (
  id                   bigint generated always as identity primary key,
  banco_id             bigint not null references bancos(id) on delete cascade,
  titulo               text not null,
  tipo                 text not null check (tipo in ('descuento','reintegro','cuotas')),
  porcentaje           numeric(5,2),
  tope_gs              numeric(12,2),   -- sin tope el comparador miente en compras grandes
  tarjetas             text[]   not null default '{}',
  dias_semana          smallint[] not null default '{}',  -- 0=domingo..6=sabado; vacio = todos
  vigente_desde        date not null,
  vigente_hasta        date not null,
  url_bases            text not null,   -- prevalecen las bases del banco: siempre enlazadas
  farmacias_aplicables bigint[] not null default '{}',    -- vacio = todas
  estado               text not null default 'pendiente'
    check (estado in ('pendiente','publicada','rechazada')),
  fuente_url           text,
  detectada_en         timestamptz not null default now(),
  check (vigente_hasta >= vigente_desde)
);

create index promos_vigencia_idx on promos_bancarias(estado, vigente_desde, vigente_hasta);

-- -------------------------------------------------------------------- vistas

-- Ultimo precio capturado por producto.
create view v_precio_actual as
select distinct on (p.producto_id)
       p.producto_id, p.precio_lista, p.precio_oferta, p.descuento_pct, p.capturado_en
from   precios p
order  by p.producto_id, p.capturado_en desc;

-- Solo promos aprobadas por humano Y vigentes hoy.
-- La expiracion es por construccion: no hay job de limpieza que pueda fallar.
create view v_promos_vigentes as
select id, banco_id, titulo, tipo, porcentaje, tope_gs, tarjetas, dias_semana,
       vigente_desde, vigente_hasta, url_bases, farmacias_aplicables
from   promos_bancarias
where  estado = 'publicada'
  and  current_date between vigente_desde and vigente_hasta;

-- GATE LEGAL — Ley 1119/97 Art. 25 inc. 10.
-- Los medicamentos de venta bajo receta y controlados se exponen como "aviso de
-- existencia en plaza": nombre, presentacion, farmacia y link. Sin precio, sin
-- porcentaje de descuento y fuera de todo ranking.
-- NO mover este filtro al frontend.
create view v_productos_publicos as
select pr.id,
       pr.farmacia_id,
       f.nombre as farmacia_nombre,
       f.slug   as farmacia_slug,
       pr.ean,
       pr.nombre,
       pr.marca,
       pr.presentacion,
       pr.categoria_id,
       pr.url_producto,
       pr.imagen_url,
       pr.condicion_venta,
       (pr.condicion_venta in ('bajo_receta','controlado')) as requiere_receta,
       case when pr.condicion_venta in ('bajo_receta','controlado')
            then null else pa.precio_lista  end as precio_lista,
       case when pr.condicion_venta in ('bajo_receta','controlado')
            then null else pa.precio_oferta end as precio_oferta,
       case when pr.condicion_venta in ('bajo_receta','controlado')
            then null else pa.descuento_pct end as descuento_pct,
       case when pr.condicion_venta in ('bajo_receta','controlado')
            then null else pa.capturado_en  end as precio_capturado_en
from   productos pr
join   farmacias f on f.id = pr.farmacia_id
left   join v_precio_actual pa on pa.producto_id = pr.id
where  pr.activo and f.activa;

-- Mejor precio final por producto, cruzando la mejor promo bancaria aplicable.
-- Precio final = oferta - LEAST(oferta * pct, tope). El tope no es una
-- optimizacion: omitirlo es informacion enganosa bajo la Ley 1334/98.
create view v_mejor_precio as
select vp.*,
       gi.grupo_id,
       mp.promo_id,
       mp.banco_id,
       mp.promo_titulo,
       mp.porcentaje as promo_porcentaje,
       mp.tope_gs    as promo_tope_gs,
       mp.url_bases  as promo_url_bases,
       case when vp.precio_oferta is null or mp.promo_id is null then vp.precio_oferta
            else vp.precio_oferta - least(vp.precio_oferta * mp.porcentaje / 100.0, mp.tope_gs)
       end as precio_final
from   v_productos_publicos vp
left   join grupo_items gi on gi.producto_id = vp.id
left   join lateral (
         select pv.id as promo_id, pv.banco_id, pv.titulo as promo_titulo,
                pv.porcentaje, pv.tope_gs, pv.url_bases
         from   v_promos_vigentes pv
         where  vp.precio_oferta is not null            -- sin precio no hay promo (Rx)
           and  (cardinality(pv.farmacias_aplicables) = 0
                 or vp.farmacia_id = any(pv.farmacias_aplicables))
         order  by least(vp.precio_oferta * pv.porcentaje / 100.0, pv.tope_gs) desc nulls last
         limit  1
       ) mp on true;

-- ---------------------------------------------------------------------- RLS

alter table farmacias        enable row level security;
alter table categorias       enable row level security;
alter table productos        enable row level security;
alter table precios          enable row level security;
alter table grupos           enable row level security;
alter table grupo_items      enable row level security;
alter table bancos           enable row level security;
alter table promos_bancarias enable row level security;

-- Sin politicas: anon y authenticated no leen ninguna tabla base.
-- El scraper escribe con la secret key, que hace bypass de RLS.
revoke all on farmacias, categorias, productos, precios,
              grupos, grupo_items, bancos, promos_bancarias
  from anon, authenticated;

-- Superficie publica: exclusivamente estas vistas.
-- Corren con permisos del owner (security_invoker off por defecto), asi que
-- leen las tablas base pese al RLS, pero solo devuelven lo que el gate permite.
grant select on v_productos_publicos, v_mejor_precio, v_promos_vigentes
  to anon, authenticated;
